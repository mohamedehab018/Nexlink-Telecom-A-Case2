from typing import Any, Dict
import jsonschema

# Tool Input JSON Schemas
VERIFY_ACCOUNT_SCHEMA = {
    "type": "object",
    "properties": {
        "account_id": {"type": "integer", "minimum": 1},
        "account_pin": {"type": "integer", "minimum": 0, "maximum": 9999}
    },
    "required": ["account_id", "account_pin"],
    "additionalProperties": False
}

GET_ACCOUNT_SCHEMA = {
    "type": "object",
    "properties": {
        "account_id": {"type": ["integer", "string"]}
    },
    "required": ["account_id"],
    "additionalProperties": False
}

LIST_TICKETS_SCHEMA = {
    "type": "object",
    "properties": {
        "account_id": {"type": "integer", "minimum": 1}
    },
    "required": ["account_id"],
    "additionalProperties": False
}

GET_EQUIPMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "account_id": {"type": "integer", "minimum": 1}
    },
    "required": ["account_id"],
    "additionalProperties": False
}

DIAGNOSE_EQUIPMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "serial_num": {"type": "string", "minLength": 1}
    },
    "required": ["serial_num"],
    "additionalProperties": False
}

NETWORK_SWEEP_SCHEMA = {
    "type": "object",
    "properties": {
        "account_id": {"type": "integer", "minimum": 1}
    },
    "required": ["account_id"],
    "additionalProperties": False
}

CREATE_TICKET_SCHEMA = {
    "type": "object",
    "properties": {
        "account_id": {"type": "integer", "minimum": 1},
        "ticket_type": {"type": "string", "enum": ["billing", "technical", "dispatch", "other"]},
        "description": {"type": "string", "minLength": 5}
    },
    "required": ["account_id", "ticket_type", "description"],
    "additionalProperties": False
}

SCHEDULE_DISPATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "account_id": {"type": "integer", "minimum": 1},
        "description": {"type": "string", "minLength": 5}
    },
    "required": ["account_id", "description"],
    "additionalProperties": False
}

APPLY_CREDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "account_id": {"type": "integer", "minimum": 1},
        "ticket_id": {"type": "integer", "minimum": 1},
        "amount_usd": {"type": "number", "minimum": 0.01, "maximum": 500.00}
    },
    "required": ["account_id", "ticket_id", "amount_usd"],
    "additionalProperties": False
}

SEARCH_ACCOUNT_SCHEMA = {
    "type": "object",
    "properties": {
        "customer_name": {"type": "string", "minLength": 1}
    },
    "required": ["customer_name"],
    "additionalProperties": False
}

UPDATE_ADDRESS_SCHEMA = {
    "type": "object",
    "properties": {
        "account_id": {"type": "integer", "minimum": 1},
        "new_address": {"type": "string", "minLength": 3, "maxLength": 200}
    },
    "required": ["account_id", "new_address"],
    "additionalProperties": False
}

TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "verify_account_identity": VERIFY_ACCOUNT_SCHEMA,
    "get_account_summary": GET_ACCOUNT_SCHEMA,
    "list_support_tickets": LIST_TICKETS_SCHEMA,
    "get_equipment_diagnostics": GET_EQUIPMENT_SCHEMA,
    "diagnose_equipment_issue": DIAGNOSE_EQUIPMENT_SCHEMA,
    "run_network_diagnostic_sweep": NETWORK_SWEEP_SCHEMA,
    "create_support_ticket": CREATE_TICKET_SCHEMA,
    "schedule_technician_dispatch": SCHEDULE_DISPATCH_SCHEMA,
    "apply_billing_credit": APPLY_CREDIT_SCHEMA,
    "search_account_by_name": SEARCH_ACCOUNT_SCHEMA,
    "update_account_address": UPDATE_ADDRESS_SCHEMA,
}


def validate_tool_input(tool_name: str, arguments: Dict[str, Any]) -> None:
    """Validates arguments against JSON schema for requested tool."""
    schema = TOOL_SCHEMAS.get(tool_name)
    if not schema:
        return
    try:
        jsonschema.validate(instance=arguments, schema=schema)
    except jsonschema.ValidationError as err:
        raise ValueError(f"Schema validation error for '{tool_name}': {err.message}")