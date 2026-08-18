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
            Dictionary with activation result
        """
        # Create or resume thread
        if account_id:
            thread_id = self.checkpoint_mgr.create_thread(account_id)
        else:
            # We'll create account first, then thread
            thread_id = None
        
        data = ActivationData(
            account_id=account_id,
            customer_name=customer_name,
            address=address,
            plan_id=plan_id,
            pin=pin
        )
        
        current_state = GraphState.START
        step = 0
        
        # Run the graph
        while current_state != GraphState.END:
            handler = self.state_handlers.get(current_state)
            if not handler:
                return {
                    "success": False,
                    "error": f"No handler for state: {current_state.value}"
                }
            
            # Save checkpoint
            if thread_id:
                run_id = self.checkpoint_mgr.create_run(thread_id) if step == 0 else run_id
                self.checkpoint_mgr.save_checkpoint(run_id, step, current_state, data)
            
            # Execute state handler
            result = handler(data)
            
            # Handle result
            if isinstance(result, dict) and result.get("error"):
                data.error = result["error"]
                current_state = GraphState.FAILURE
            elif isinstance(result, GraphState):
                current_state = result
            else:
                # Get next state from transition
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
        if thread_id:
            self.checkpoint_mgr.update_run_status(run_id, "completed")
            self.checkpoint_mgr.update_thread_status(thread_id, "completed")
        
        return {
            "success": True,
            "account_id": data.account_id,
            "thread_id": thread_id,
            "steps": step,
            "data": data.to_dict()
        }

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

    def _handle_hitl_wait(self, data: ActivationData) -> GraphState:
        """Handle human-in-the-loop wait."""
        data.current_step = "hitl_wait"
        
        # Create approval request
        task_id = self.hitl_mgr.create_approval_request(
            run_id=0,  # Will be set by checkpoint system
            thread_id=0,  # Will be set by checkpoint system
            account_id=data.account_id,
            task_type="equipment_cost",
            description=data.hitl_reason or "Equipment approval required"
        )
        
        data.add_message("system", f"Waiting for approval (Task #{task_id})")
        
        # In real system, this would pause and wait for webhook
        # For demo, we auto-approve
        self.hitl_mgr.approve_task(task_id, "system", "Auto-approved for demo")
        data.hitl_approved = True
        
        return GraphState.CONFIGURE_EQUIPMENT

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
        
        # Log failure
        failure_id = self.failure_mgr.log_failure(
            run_id=0,
            thread_id=0,
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

    def resume_from_checkpoint(self, run_id: int) -> Dict[str, Any]:
        """Resume a graph from a checkpoint.
        
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
