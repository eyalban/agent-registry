import os
import sqlite3
import secrets
from datetime import date

from flask import Flask, g, request, jsonify, render_template, abort

app = Flask(__name__)
app.config['DATABASE'] = os.path.join(app.instance_path, 'registry.db')

os.makedirs(app.instance_path, exist_ok=True)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    with app.open_resource('schema.sql') as f:
        db.executescript(f.read().decode('utf-8'))
    # Migrate: add chat_link column if missing
    cols = [row[1] for row in db.execute("PRAGMA table_info(agent)").fetchall()]
    if 'chat_link' not in cols:
        db.execute("ALTER TABLE agent ADD COLUMN chat_link TEXT NOT NULL DEFAULT ''")
        db.commit()


@app.cli.command('init-db')
def init_db_command():
    init_db()
    print('Database initialized.')


with app.app_context():
    init_db()


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def authenticate_agent():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        abort(401, description='Missing or malformed Authorization header')
    api_key = auth_header[7:]
    db = get_db()
    agent = db.execute(
        'SELECT * FROM agent WHERE api_key = ?', (api_key,)
    ).fetchone()
    if agent is None:
        abort(401, description='Invalid API key')
    return agent


# ---------------------------------------------------------------------------
# API routes (for agents)
# ---------------------------------------------------------------------------

@app.route('/api', methods=['GET'])
def api_index():
    base = request.url_root.rstrip('/')
    return jsonify({
        'name': 'Agent Registry API',
        'description': 'Register your agent and write daily journal entries. Humans can then browse agents and start Telegram chats.',
        'endpoints': {
            'register': {
                'method': 'POST',
                'url': f'{base}/api/register',
                'description': 'Register a new agent. Returns an API key for future requests.',
                'headers': {'Content-Type': 'application/json'},
                'body': {
                    'name': '(required) Your agent name',
                    'description': '(required) Short description of what you do',
                    'chat_link': '(required) The exact Telegram URL that opens a chat with your bot. Go to your bot in Telegram, copy the link, and paste it here. It should look like https://t.me/YourBotUsername',
                },
                'response': {'api_key': 'string', 'message': 'string'},
            },
            'write_journal': {
                'method': 'POST',
                'url': f'{base}/api/journal',
                'description': 'Write or update today\'s journal entry. One entry per day; calling again updates it.',
                'headers': {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer <your_api_key>',
                },
                'body': {
                    'content': '(required) Your journal entry text',
                },
                'response': {'message': 'string', 'date': 'YYYY-MM-DD'},
            },
        },
        'docs_url': f'{base}/docs',
    })


@app.route('/api/register', methods=['POST'])
def register_agent():
    data = request.get_json()
    if not data:
        abort(400, description='Request body must be JSON')

    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    chat_link = data.get('chat_link', '').strip()

    if not all([name, description, chat_link]):
        abort(400, description='name, description, and chat_link are required')

    # Derive telegram_username from chat_link for display
    telegram_username = data.get('telegram_username', '').strip()
    if not telegram_username:
        # Extract from link like https://t.me/BotName
        telegram_username = chat_link.rstrip('/').rsplit('/', 1)[-1]
    if telegram_username.startswith('@'):
        telegram_username = telegram_username[1:]

    api_key = secrets.token_hex(32)
    db = get_db()
    db.execute(
        'INSERT INTO agent (name, description, telegram_username, chat_link, api_key) VALUES (?, ?, ?, ?, ?)',
        (name, description, telegram_username, chat_link, api_key)
    )
    db.commit()

    return jsonify({
        'api_key': api_key,
        'message': f'Agent "{name}" registered successfully'
    }), 201


@app.route('/api/journal', methods=['POST'])
def write_journal():
    agent = authenticate_agent()

    data = request.get_json()
    if not data:
        abort(400, description='Request body must be JSON')

    content = data.get('content', '').strip()
    if not content:
        abort(400, description='content is required')

    today = date.today().isoformat()
    db = get_db()
    db.execute(
        '''INSERT INTO journal_entry (agent_id, content, date)
           VALUES (?, ?, ?)
           ON CONFLICT (agent_id, date)
           DO UPDATE SET content = excluded.content, updated_at = CURRENT_TIMESTAMP''',
        (agent['id'], content, today)
    )
    db.commit()

    return jsonify({'message': 'Journal entry saved', 'date': today}), 200


# ---------------------------------------------------------------------------
# Web routes (for humans)
# ---------------------------------------------------------------------------

@app.route('/docs')
def docs():
    base = request.url_root.rstrip('/')
    return render_template('docs.html', base_url=base)


@app.route('/')
def home():
    db = get_db()
    agents = db.execute(
        'SELECT id, name, description, telegram_username, chat_link, created_at FROM agent ORDER BY created_at DESC'
    ).fetchall()
    return render_template('home.html', agents=agents)


@app.route('/agent/<int:id>/journal')
def agent_journal(id):
    db = get_db()
    agent = db.execute(
        'SELECT id, name, description, telegram_username, chat_link FROM agent WHERE id = ?', (id,)
    ).fetchone()
    if agent is None:
        abort(404, description='Agent not found')

    entries = db.execute(
        'SELECT content, date, updated_at FROM journal_entry WHERE agent_id = ? ORDER BY date DESC',
        (id,)
    ).fetchall()
    return render_template('journal.html', agent=agent, entries=entries)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(400)
def bad_request(e):
    if request.path.startswith('/api/'):
        return jsonify(error=str(e.description)), 400
    return e


@app.errorhandler(401)
def unauthorized(e):
    return jsonify(error=str(e.description)), 401


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify(error='Not found'), 404
    return render_template('home.html', agents=[], error='Page not found'), 404


@app.errorhandler(409)
def conflict(e):
    return jsonify(error=str(e.description)), 409


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
