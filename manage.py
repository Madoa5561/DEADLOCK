"""運営用のローカル操作 管理機能は公開しない """
import argparse
from pathlib import Path
from arena.store import AccountStore


def main():
    parser = argparse.ArgumentParser(description="DEADLOCK local moderation")
    parser.add_argument('command', choices=['reports', 'ban', 'unban'])
    parser.add_argument('--user-id')
    parser.add_argument('--database', default=str(Path(__file__).parent / 'data' / 'arena.sqlite3'))
    args = parser.parse_args()
    store = AccountStore(args.database)
    with store.connect() as db:
        if args.command == 'reports':
            for row in db.execute('SELECT id,user_id,target,reason,created FROM reports ORDER BY id DESC LIMIT 100'):
                print(dict(row))
        else:
            if not args.user_id or not store.get(args.user_id):
                parser.error('有効な --user-id を指定してください')
            db.execute('UPDATE users SET banned=? WHERE id=?', (int(args.command == 'ban'), args.user_id))
            if args.command == 'ban':
                db.execute('DELETE FROM sessions WHERE user_id=?', (args.user_id,))
            print('Updated:', args.user_id, args.command)


if __name__ == '__main__':
    main()
