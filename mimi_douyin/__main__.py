import argparse
import asyncio
import json
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description='与bot刷抖音：不需要 AstrBot 的本地运行入口。')
    parser.add_argument('command',choices=('serve','check'),nargs='?',default='serve')
    parser.add_argument('--data-dir',default=str(Path.cwd()/'data'))
    parser.add_argument('--port',type=int,default=8787)
    args=parser.parse_args()
    if args.command=='check':
        from .config import Settings
        from .runtime import RuntimeEnvironment
        config=Settings(args.data_dir)
        print(json.dumps(asyncio.run(RuntimeEnvironment(config,config.data_dir).diagnose()),ensure_ascii=False,indent=2));return
    import uvicorn
    from .app import create_app
    print(f'Mimi 本地设置页：http://127.0.0.1:{args.port} （首次打开后配置模型和登录）',flush=True)
    uvicorn.run(create_app(args.data_dir),host='127.0.0.1',port=args.port,log_level='warning',access_log=False)

if __name__=='__main__':main()
