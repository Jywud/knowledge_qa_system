"""维护窗口手动执行；--plan 永不建表或改数据。"""
import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine
from app.services.role_migration_service import apply_migration, plan_migration


async def main(apply: bool) -> None:
    try:
        if apply:
            print('请先停止旧后端，并确认已备份数据库和原始上传文件。')
            changed = await apply_migration(engine)
            print('角色权限迁移完成。' if changed else '迁移标记已存在，本次未修改数据或权限。')
        else:
            print(json.dumps(await plan_migration(engine), ensure_ascii=False, indent=2))
    finally:
        await engine.dispose()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='角色权限迁移（不会自动给普通账号授权）')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--plan', action='store_true', help='只读输出数据计数')
    mode.add_argument('--apply', action='store_true', help='明确执行事务迁移')
    args = parser.parse_args()
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main(args.apply))
    except RuntimeError as exc:
        print(f'迁移未完成：{exc}', file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        # 不输出连接字符串、SQL 参数、密码或正文。
        print(f'迁移未完成（{type(exc).__name__}），请检查数据库结构和连接状态；事务已回滚。', file=sys.stderr)
        sys.exit(1)
