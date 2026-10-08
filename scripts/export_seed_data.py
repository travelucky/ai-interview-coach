import argparse
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )


def export_seed_data(source, output_dir):
    source = Path(source).resolve()
    output_dir = Path(output_dir).resolve()
    if not source.is_file():
        raise FileNotFoundError(f'Source database not found: {source}')

    connection = sqlite3.connect(source)
    connection.row_factory = sqlite3.Row
    try:
        positions = [
            dict(row)
            for row in connection.execute(
                'SELECT code, name, description FROM position ORDER BY id'
            )
        ]
        questions = [
            dict(row)
            for row in connection.execute(
                '''
                SELECT p.code AS position_code,
                       q.type,
                       q.content,
                       q.reference_answer,
                       q.difficulty,
                       q.tags
                  FROM question q
                  JOIN position p ON p.id = q.position_id
              ORDER BY q.id
                '''
            )
        ]
        knowledge = [
            dict(row)
            for row in connection.execute(
                '''
                SELECT position_code, title, content, tags
                  FROM knowledge
              ORDER BY id
                '''
            )
        ]
    finally:
        connection.close()

    _write_json(output_dir / 'positions.json', positions)
    _write_json(output_dir / 'questions.json', questions)
    _write_json(output_dir / 'knowledge.json', knowledge)
    print(
        'Exported seed data: '
        f'{len(positions)} positions, {len(questions)} questions, '
        f'{len(knowledge)} knowledge entries.'
    )


def main():
    parser = argparse.ArgumentParser(
        description='Export non-sensitive seed data from a legacy SQLite database.'
    )
    parser.add_argument(
        '--source',
        default=str(ROOT / 'data' / 'interview.db'),
        help='Path to the source SQLite database.',
    )
    parser.add_argument(
        '--output',
        default=str(ROOT / 'seed'),
        help='Directory for generated JSON files.',
    )
    args = parser.parse_args()
    export_seed_data(args.source, args.output)


if __name__ == '__main__':
    main()

