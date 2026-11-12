"""维护窗口显式增加会话范围字段。"""
import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import engine
from app.services.chat_scope_migration_service import apply_migration, plan_migration


async def main(apply: bool) -> None:
    try:
        if apply:
            print("请先停止后端，并备份数据库与原始文件。")
            changed = await apply_migration(engine)
            print("跨库会话范围初始化完成。" if changed else "已初始化，本次未修改数据。")
        else:
            print(json.dumps(await plan_migration(engine), ensure_ascii=False, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="增加跨库会话范围字段")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main(args.apply))
    except RuntimeError as exc:
        print(f"初始化未完成：{exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"初始化未完成（{type(exc).__name__}），请核对数据库状态；事务已回滚。", file=sys.stderr)
        sys.exit(1)
