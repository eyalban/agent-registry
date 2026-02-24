CREATE TABLE IF NOT EXISTS agent (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    description TEXT NOT NULL,
    telegram_username TEXT NOT NULL,
    chat_link  TEXT NOT NULL DEFAULT '',
    api_key    TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS journal_entry (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id   INTEGER NOT NULL,
    content    TEXT NOT NULL,
    date       DATE NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agent (id),
    UNIQUE (agent_id, date)
);
