CREATE TABLE SUBSCRIPTION_PLANS (
    plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    monthly_cost_usd REAL NOT NULL,
    max_speed_mbps INTEGER NOT NULL
);

CREATE TABLE ACCOUNTS (
    account_id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    customer_name TEXT NOT NULL,
    account_pin TEXT NOT NULL,
    address TEXT NOT NULL,
    FOREIGN KEY (plan_id) REFERENCES SUBSCRIPTION_PLANS(plan_id)
);

CREATE TABLE EQUIPMENT (
    serial_num TEXT PRIMARY KEY,
    account_id INTEGER NOT NULL,
    model_type TEXT NOT NULL,
    status TEXT NOT NULL,
    last_error_log TEXT,
    FOREIGN KEY (account_id) REFERENCES ACCOUNTS(account_id)
);

CREATE TABLE SUPPORT_TICKETS (
    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    ticket_type TEXT NOT NULL CHECK(ticket_type IN ('billing', 'technical', 'dispatch', 'other')),
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'ongoing', 'closed')),
    description TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES ACCOUNTS(account_id)
);