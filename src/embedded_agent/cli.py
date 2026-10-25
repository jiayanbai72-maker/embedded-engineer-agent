import argparse
import json
from pathlib import Path
from .application import Application
from .model import configured_model


def main():
    parser = argparse.ArgumentParser(description='通用嵌入式 Agent 架构入口')
    parser.add_argument('--root', type=Path, default=Path(__file__).absolute().parents[2])
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create')
    create.add_argument('--description', required=True)
    analyze = commands.add_parser('analyze')
    analyze.add_argument('--description', help='省略时在终端输入需求')
    supplement = commands.add_parser('supplement')
    supplement.add_argument('project_id')
    supplement.add_argument('--message', required=True)
    for command in ('show', 'step', 'retry'):
        sub = commands.add_parser(command)
        sub.add_argument('project_id')
    search = commands.add_parser('search')
    search.add_argument('--query', required=True)
    search.add_argument('--scope', choices=('general', 'ecosystem', 'device', 'case', 'all'), default='general')
    commands.add_parser('capabilities')
    args = parser.parse_args()
    try:
        model = configured_model() if args.command in ('analyze', 'supplement', 'step', 'capabilities') else None
        app = Application(args.root, model=model)
        if args.command == 'create':
            output = app.store.create(args.description).to_dict()
        elif args.command == 'analyze':
            description = args.description if args.description is not None else input('请描述你想做的嵌入式项目：\n')
            output = app.analyze(description).to_dict()
        elif args.command == 'supplement':
            output = app.supplement(args.project_id, args.message).to_dict()
        elif args.command == 'show':
            output = app.store.load(args.project_id).to_dict()
        elif args.command in ('step', 'retry'):
            output = getattr(app.workflow, args.command)(args.project_id).to_dict()
        elif args.command == 'search':
            output = app.tools.execute('knowledge.search', {'query': args.query, 'scope': args.scope})
        else:
            output = {'tools': app.tools.capabilities(), 'model': 'configured' if model else 'not_configured', 'hardware': 'not_configured'}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
