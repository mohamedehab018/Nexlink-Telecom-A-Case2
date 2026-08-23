"""Order-to-Activation State Graph.

Main state machine for customer service activation workflow.
"""
from __future__ import annotations
import json
from typing import Optional, Dict, Any, Callable
from .states import GraphState, ActivationData
from .checkpoint import CheckpointManager
from .hitl import HITLManager
from .failure import FailureManager
from .tools import (
    create_account, assign_equipment, configure_equipment,
    activate_service, send_welcome_message, check_equipment_available
)


# ---------------------------------------------------------------------------
# Sentinel returned by _handle_hitl_wait to signal a durable pause
# ---------------------------------------------------------------------------
class _PausedForHITL:
    """Returned by _handle_hitl_wait when the graph durably pauses."""


_PAUSED = _PausedForHITL()


class ActivationGraph:
    """State graph for customer service activation."""

    def __init__(self, db_path: str = "db/nexlink.db"):
        self.db_path = db_path
        self.checkpoint_mgr = CheckpointManager(db_path)
        self.hitl_mgr = HITLManager(db_path)
        self.failure_mgr = FailureManager(db_path)

        self.state_handlers: Dict[GraphState, Callable] = {
            GraphState.START: self._handle_start,
            GraphState.CREATE_ACCOUNT: self._handle_create_account,
            GraphState.VERIFY_IDENTITY: self._handle_verify_identity,
            GraphState.CHECK_EQUIPMENT: self._handle_check_equipment,
            GraphState.WAIT_FOR_EQUIPMENT: self._handle_wait_for_equipment,
            GraphState.CONFIGURE_EQUIPMENT: self._handle_configure_equipment,
            GraphState.HITL_WAIT: self._handle_hitl_wait,
            GraphState.TEST_CONNECTION: self._handle_test_connection,
            GraphState.ACTIVATE_SERVICE: self._handle_activate_service,
            GraphState.SEND_WELCOME: self._handle_send_welcome,
            GraphState.FAILURE: self._handle_failure,
            GraphState.RETRY: self._handle_retry,
            GraphState.END: self._handle_end,
        }

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def run(
        self,
        customer_name: str,
        address: str,
        plan_id: int,
        pin: str,
        account_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Run the activation graph.

        Args:
            customer_name: Customer's full name
            address: Installation address
            plan_id: Subscription plan ID
            pin: 4-digit security PIN
            account_id: Existing account ID (if resuming)

        Returns:
            Dictionary with activation result. When HITL approval is required,
            returns ``{"paused": True, "task_id": ..., "run_id": ..., ...}``
            instead of completing.
        """
        data = ActivationData(
            account_id=account_id,
            customer_name=customer_name,
            address=address,
            plan_id=plan_id,
            pin=pin
        )

        # thread_id / run_id are created lazily once we have an account_id.
        # They are stored on data so state handlers can read them.
        thread_id: Optional[int] = None
        run_id: Optional[int] = None

        if account_id:
            thread_id = self.checkpoint_mgr.create_thread(account_id)
            data.thread_id = thread_id

        current_state = GraphState.START
        step = 0

        while current_state != GraphState.END:
            handler = self.state_handlers.get(current_state)
            if not handler:
                return {
                    "success": False,
                    "error": f"No handler for state: {current_state.value}"
                }

            # ------ Lazy thread/run creation (triggered after account exists) --
            if data.account_id and thread_id is None:
                thread_id = self.checkpoint_mgr.create_thread(data.account_id)
                data.thread_id = thread_id

            if thread_id and run_id is None:
                run_id = self.checkpoint_mgr.create_run(thread_id)
                data.run_id = run_id

            # Save checkpoint before executing the handler
            if run_id:
                self.checkpoint_mgr.save_checkpoint(run_id, step, current_state, data)

            # Execute state handler
            result = handler(data)

            # Detect durable HITL pause
            if isinstance(result, _PausedForHITL):
                # Run is already set to 'paused' inside _handle_hitl_wait
                return {
                    "paused": True,
                    "task_id": data.hitl_task_id,
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "account_id": data.account_id,
                    "message": (
                        f"Graph paused waiting for HITL approval "
                        f"(Task #{data.hitl_task_id}). "
                        f"Call resume_after_hitl({run_id}) once decided."
                    ),
                    "data": data.to_dict(),
                }

            # Handle result
            if isinstance(result, dict) and result.get("error"):
                data.error = result["error"]
                current_state = GraphState.FAILURE
            elif isinstance(result, GraphState):
                current_state = result
            else:
                current_state = self._get_next_state(current_state, data)

            step += 1

            # Safety check for infinite loops
            if step > 20:
                return {
                    "success": False,
                    "error": "Maximum steps exceeded",
                    "last_state": current_state.value,
                    "data": data.to_dict()
                }

        # Update final status
        if run_id:
            self.checkpoint_mgr.update_run_status(run_id, "completed")
        if thread_id:
            self.checkpoint_mgr.update_thread_status(thread_id, "completed")

        return {
            "success": True,
            "account_id": data.account_id,
            "thread_id": thread_id,
            "run_id": run_id,
            "steps": step,
            "data": data.to_dict()
        }

    def resume_after_hitl(self, run_id: int) -> Dict[str, Any]:
        """Resume a graph that was paused at HITL_WAIT after a human decision.

        Loads the checkpoint for *run_id*, reads the HITL decision, applies
        it to the activation data, then re-enters the graph loop from the
        appropriate post-decision state.

        Args:
            run_id: The run that was paused waiting for HITL.

        Returns:
            Same structure as ``run()``, either a success/failure result or
            (unexpectedly) another pause dict.
        """
        # Validate the run is genuinely paused
        run_meta = self.checkpoint_mgr.get_paused_run(run_id)
        if not run_meta:
            return {
                "success": False,
                "error": f"Run {run_id} is not in 'paused' state or does not exist"
            }

        # Load the last saved checkpoint
        checkpoint = self.checkpoint_mgr.load_checkpoint(run_id)
        if not checkpoint:
            return {
                "success": False,
                "error": f"No checkpoint found for run {run_id}"
            }

        _saved_state, data = checkpoint
        thread_id = run_meta["thread_id"]

        # Restore run/thread on data (may have been saved without them on old runs)
        if not data.run_id:
            data.run_id = run_id
        if not data.thread_id:
            data.thread_id = thread_id

        # Read the HITL decision
        if not data.hitl_task_id:
            return {
                "success": False,
                "error": "No hitl_task_id stored in checkpoint — cannot read decision"
            }

        status_info = self.hitl_mgr.check_approval_status(data.hitl_task_id)
        if not status_info.get("exists"):
            return {
                "success": False,
                "error": f"HITL task #{data.hitl_task_id} not found"
            }

        decision_status = status_info["status"]
        if decision_status == "pending":
            return {
                "success": False,
                "error": f"HITL task #{data.hitl_task_id} has not been decided yet"
            }

        # Apply decision and determine re-entry state
        if decision_status in ("approved", "modified"):
            data.hitl_approved = True
            data.add_message(
                "system",
                f"HITL task #{data.hitl_task_id} {decision_status} by "
                f"{status_info.get('admin_id', 'unknown')}"
            )
            current_state = GraphState.CONFIGURE_EQUIPMENT
        else:
            # rejected
            data.hitl_approved = False
            data.failure_reason = (
                f"HITL task #{data.hitl_task_id} rejected: "
                f"{status_info.get('admin_notes', 'No reason given')}"
            )
            data.add_message("system", data.failure_reason)
            current_state = GraphState.FAILURE

        # Mark run as running again before re-entering loop
        self.checkpoint_mgr.update_run_status(run_id, "running")

        step = 100  # offset so step numbers don't collide with original steps

        while current_state != GraphState.END:
            handler = self.state_handlers.get(current_state)
            if not handler:
                return {
                    "success": False,
                    "error": f"No handler for state: {current_state.value}"
                }

            self.checkpoint_mgr.save_checkpoint(run_id, step, current_state, data)

            result = handler(data)

            # Detect another HITL pause (edge case)
            if isinstance(result, _PausedForHITL):
                return {
                    "paused": True,
                    "task_id": data.hitl_task_id,
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "account_id": data.account_id,
                    "message": (
                        f"Graph paused again waiting for HITL approval "
                        f"(Task #{data.hitl_task_id})."
                    ),
                    "data": data.to_dict(),
                }

            if isinstance(result, dict) and result.get("error"):
                data.error = result["error"]
                current_state = GraphState.FAILURE
            elif isinstance(result, GraphState):
                current_state = result
            else:
                current_state = self._get_next_state(current_state, data)

            step += 1
            if step > 130:
                return {
                    "success": False,
                    "error": "Maximum steps exceeded during resume",
                    "last_state": current_state.value,
                    "data": data.to_dict()
                }

        self.checkpoint_mgr.update_run_status(run_id, "completed")
        self.checkpoint_mgr.update_thread_status(thread_id, "completed")

        return {
            "success": True,
            "account_id": data.account_id,
            "thread_id": thread_id,
            "run_id": run_id,
            "steps": step,
            "data": data.to_dict()
        }

    def resume_from_checkpoint(self, run_id: int) -> Dict[str, Any]:
        """Resume a graph from a checkpoint (crash-recovery path).

        Args:
            run_id: Run ID to resume from

        Returns:
            Resume result
        """
        checkpoint = self.checkpoint_mgr.load_checkpoint(run_id)

        if not checkpoint:
            return {
                "success": False,
                "error": "No checkpoint found"
            }

        state, data = checkpoint

        # Resume from the saved state
        handler = self.state_handlers.get(state)
        if handler:
            result = handler(data)
            return {
                "success": True,
                "resumed_from": state.value,
                "data": data.to_dict()
            }

        return {
            "success": False,
            "error": f"Cannot resume from state: {state.value}"
        }

    # ------------------------------------------------------------------
    # State handlers
    # ------------------------------------------------------------------

    def _handle_start(self, data: ActivationData) -> GraphState:
        """Handle start state."""
        data.current_step = "start"
        data.add_message("system", "Starting activation process")

        if data.account_id:
            return GraphState.VERIFY_IDENTITY
        return GraphState.CREATE_ACCOUNT

    def _handle_create_account(self, data: ActivationData) -> GraphState:
        """Handle account creation."""
        data.current_step = "create_account"

        result = create_account(
            customer_name=data.customer_name,
            address=data.address,
            plan_id=data.plan_id,
            pin=data.pin,
            db_path=self.db_path
        )

        if result["success"]:
            data.account_id = result["account_id"]
            data.add_message("system", f"Account #{data.account_id} created")
            return GraphState.VERIFY_IDENTITY
        else:
            data.failure_reason = result.get("error", "Account creation failed")
            return GraphState.FAILURE

    def _handle_verify_identity(self, data: ActivationData) -> GraphState:
        """Handle identity verification."""
        data.current_step = "verify_identity"

        # For activation, we assume identity is verified at signup
        data.verified = True
        data.add_message("system", "Identity verified")
        return GraphState.CHECK_EQUIPMENT

    def _handle_check_equipment(self, data: ActivationData) -> GraphState:
        """Handle equipment check."""
        data.current_step = "check_equipment"

        # Check what equipment the customer needs
        # For now, default to WiFi-V3 for residential
        model_type = "WiFi-V3"

        availability = check_equipment_available(model_type, self.db_path)

        if not availability["available"]:
            data.failure_reason = availability.get("error", "Equipment not available")
            return GraphState.FAILURE

        data.equipment_model = model_type

        # If equipment requires approval (cost > $100), go to HITL
        if availability.get("requires_approval", False):
            data.hitl_reason = f"Equipment cost: ${availability.get('cost_usd', 0)}"
            return GraphState.HITL_WAIT

        return GraphState.CONFIGURE_EQUIPMENT

    def _handle_wait_for_equipment(self, data: ActivationData) -> GraphState:
        """Handle waiting for equipment assignment."""
        data.current_step = "wait_for_equipment"

        # Check if equipment is now available
        # In real system, this would poll or receive webhook
        # For now, assume equipment is assigned
        data.equipment_serial = f"EQ-{data.account_id}-001"
        data.add_message("system", f"Equipment {data.equipment_serial} assigned")
        return GraphState.CONFIGURE_EQUIPMENT

    def _handle_configure_equipment(self, data: ActivationData) -> GraphState:
        """Handle equipment configuration."""
        data.current_step = "configure_equipment"

        if not data.equipment_serial:
            # Assign equipment first
            result = assign_equipment(
                account_id=data.account_id,
                serial_num=f"EQ-{data.account_id}-001",
                model_type=data.equipment_model or "WiFi-V3",
                db_path=self.db_path
            )

            if not result["success"]:
                data.failure_reason = result.get("error", "Equipment assignment failed")
                return GraphState.FAILURE

            data.equipment_serial = result["serial_num"]

        # Configure equipment
        result = configure_equipment(
            serial_num=data.equipment_serial,
            config={"plan_id": data.plan_id},
            db_path=self.db_path
        )

        if result["success"]:
            data.configured = True
            data.add_message("system", f"Equipment {data.equipment_serial} configured")
            return GraphState.TEST_CONNECTION
        else:
            data.failure_reason = result.get("error", "Configuration failed")
            return GraphState.FAILURE

    def _handle_hitl_wait(self, data: ActivationData) -> "_PausedForHITL | GraphState":
        """Handle human-in-the-loop wait — durably pause the graph.

        Creates a HITL approval request, saves a checkpoint at this state,
        marks the run as 'paused', stores the task_id on *data*, and returns
        ``_PAUSED`` so the outer loop knows to break and surface a paused result
        to the caller.  Execution resumes via ``resume_after_hitl(run_id)``.
        """
        data.current_step = "hitl_wait"

        run_id = data.run_id or 0
        thread_id = data.thread_id or 0

        # Create the HITL approval request with real run/thread IDs
        task_id = self.hitl_mgr.create_approval_request(
            run_id=run_id,
            thread_id=thread_id,
            account_id=data.account_id,
            task_type="equipment_cost",
            description=data.hitl_reason or "Equipment approval required",
            state_data=data.to_dict(),
        )

        data.hitl_task_id = task_id
        data.add_message("system", f"Graph paused — waiting for HITL approval (Task #{task_id})")

        # Persist the paused state so resume_after_hitl can reload it.
        # Step -1 is used so this checkpoint sorts after normal steps but is
        # clearly identifiable as the pause checkpoint.
        if run_id:
            self.checkpoint_mgr.save_checkpoint(run_id, -1, GraphState.HITL_WAIT, data)
            self.checkpoint_mgr.update_run_status(run_id, "paused")

        return _PAUSED

    def _handle_test_connection(self, data: ActivationData) -> GraphState:
        """Handle connection testing."""
        data.current_step = "test_connection"

        # Simulate connection test
        # In real system, this would call run_network_diagnostic_sweep
        test_passed = True  # Simulate success

        if test_passed:
            data.tested = True
            data.add_message("system", "Connection test passed")
            return GraphState.ACTIVATE_SERVICE
        else:
            data.failure_reason = "Connection test failed"
            return GraphState.FAILURE

    def _handle_activate_service(self, data: ActivationData) -> GraphState:
        """Handle service activation."""
        data.current_step = "activate_service"

        result = activate_service(
            account_id=data.account_id,
            db_path=self.db_path
        )

        if result["success"]:
            data.activated = True
            data.add_message("system", "Service activated")
            return GraphState.SEND_WELCOME
        else:
            data.failure_reason = result.get("error", "Activation failed")
            return GraphState.FAILURE

    def _handle_send_welcome(self, data: ActivationData) -> GraphState:
        """Handle welcome message."""
        data.current_step = "send_welcome"

        result = send_welcome_message(
            account_id=data.account_id,
            db_path=self.db_path
        )

        if result["success"]:
            data.add_message("system", "Welcome message sent")
            return GraphState.END
        else:
            # Welcome message failure is not critical
            data.add_message("system", "Welcome message failed (non-critical)")
            return GraphState.END

    def _handle_failure(self, data: ActivationData) -> GraphState:
        """Handle failure state."""
        data.current_step = "failure"

        run_id = data.run_id or 0
        thread_id = data.thread_id or 0

        # Log failure with real IDs
        self.failure_mgr.log_failure(
            run_id=run_id,
            thread_id=thread_id,
            account_id=data.account_id or 0,
            failure_type="activation",
            failure_step=data.current_step,
            failure_reason=data.failure_reason or "Unknown error",
            state_data=data.to_dict()
        )

        # Create support ticket
        ticket_result = self.failure_mgr.create_failure_ticket(
            account_id=data.account_id or 0,
            failure_type="activation",
            failure_reason=data.failure_reason or "Unknown error"
        )

        if ticket_result["success"]:
            data.ticket_id = ticket_result["ticket_id"]

        # Do not retry human HITL rejections
        if data.hitl_task_id and not data.hitl_approved:
            data.add_message("system", f"Activation aborted due to HITL rejection: {data.failure_reason}")
            return GraphState.END

        # Check if we should retry
        if self.failure_mgr.should_retry(data.retry_count, data.max_retries):
            return GraphState.RETRY
        else:
            data.add_message("system", f"Activation failed after {data.retry_count} retries")
            return GraphState.END

    def _handle_retry(self, data: ActivationData) -> GraphState:
        """Handle retry logic."""
        data.current_step = "retry"
        data.retry_count += 1

        data.add_message("system", f"Retry attempt {data.retry_count}/{data.max_retries}")

        # Reset error state
        data.error = None
        data.failure_reason = None

        # Go back to appropriate state based on where we failed
        if data.current_step == "configure_equipment":
            return GraphState.CHECK_EQUIPMENT
        elif data.current_step == "test_connection":
            return GraphState.CONFIGURE_EQUIPMENT
        elif data.current_step == "activate_service":
            return GraphState.TEST_CONNECTION
        else:
            return GraphState.CHECK_EQUIPMENT

    def _handle_end(self, data: ActivationData) -> GraphState:
        """Handle end state."""
        data.current_step = "end"
        data.add_message("system", "Activation process completed")
        return GraphState.END

    def _get_next_state(self, current_state: GraphState, data: ActivationData) -> GraphState:
        """Get next state based on current state and data."""
        # This is handled by individual state handlers
        # This method is a fallback
        return GraphState.END

