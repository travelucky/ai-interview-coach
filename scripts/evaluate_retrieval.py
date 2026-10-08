import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.services.embedding_service import refresh_knowledge_embeddings  # noqa: E402
from app.services.retrieval_service import retrieve_knowledge  # noqa: E402


def _matches(item, expected):
    title = (item.get('title') or '').lower()
    return any(value.lower() in title for value in expected)


def evaluate(cases, mode):
    relevant = [case for case in cases if not case.get('expected_empty')]
    negatives = [case for case in cases if case.get('expected_empty')]
    top1_hits = 0
    top3_hits = 0
    negative_empty = 0
    details = []
    for case in cases:
        results = retrieve_knowledge(
            case['position_code'],
            case['query'],
            limit=3,
            enable_embedding=(mode == 'hybrid'),
        )
        expected = case.get('expected_title_contains') or []
        top1 = bool(results and _matches(results[0], expected)) if expected else False
        top3 = any(_matches(item, expected) for item in results) if expected else False
        is_empty = not results
        top1_hits += int(top1)
        top3_hits += int(top3)
        negative_empty += int(bool(case.get('expected_empty')) and is_empty)
        details.append({
            'id': case['id'],
            'expected_empty': bool(case.get('expected_empty')),
            'top1_hit': top1,
            'top3_hit': top3,
            'returned': [
                {
                    'id': item['id'],
                    'title': item['title'],
                    'score': item['score'],
                    'method': item['retrieval']['method'],
                    'embedding_cosine': item['retrieval']['embedding_cosine'],
                }
                for item in results
            ],
        })
    return {
        'mode': mode,
        'case_count': len(cases),
        'relevant_count': len(relevant),
        'negative_count': len(negatives),
        'top1_accuracy': round(top1_hits / max(1, len(relevant)), 4),
        'top3_recall': round(top3_hits / max(1, len(relevant)), 4),
        'negative_rejection_rate': round(negative_empty / max(1, len(negatives)), 4),
        'details': details,
    }


def main():
    parser = argparse.ArgumentParser(description='Evaluate RAG retrieval deterministically.')
    parser.add_argument('--mode', choices=('lexical', 'hybrid'), default='lexical')
    parser.add_argument('--refresh-embeddings', action='store_true')
    parser.add_argument('--details', action='store_true')
    args = parser.parse_args()
    cases = json.loads((ROOT / 'seed' / 'retrieval_eval.json').read_text(encoding='utf-8'))
    app = create_app()
    with app.app_context():
        if args.refresh_embeddings:
            refresh = refresh_knowledge_embeddings()
            print(json.dumps({'embedding_refresh': refresh}, ensure_ascii=False))
        result = evaluate(cases, args.mode)
    if not args.details:
        result.pop('details', None)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
