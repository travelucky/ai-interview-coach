import argparse
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.models import Position, Question  # noqa: E402
from app.services.scoring_service import _local_question_score  # noqa: E402


def _band(score):
    if score >= 70:
        return 'high'
    if score >= 40:
        return 'medium'
    return 'low'


def evaluate(details=False):
    cases = json.loads(
        (ROOT / 'seed' / 'scoring_calibration.json').read_text(encoding='utf-8')
    )
    app = create_app()
    rows = []
    with app.app_context():
        for case in cases:
            position = Position.get_by_code(case['position_code'])
            question = Question.query.filter_by(
                position_id=position.id,
                content=case['question'],
            ).first() if position else None
            if question is None:
                raise RuntimeError('Calibration question not found: ' + case['question'])
            for expected_band, answer in case['answers'].items():
                result = _local_question_score(question, answer)
                rows.append({
                    'position_code': case['position_code'],
                    'question': case['question'],
                    'expected_band': expected_band,
                    'score': result['score'],
                    'actual_band': _band(result['score']),
                })
    confusion = Counter(
        f"{row['expected_band']}->{row['actual_band']}" for row in rows
    )
    output = {
        'scoring_version': 'mvp-v3',
        'sample_count': len(rows),
        'band_accuracy': round(sum(
            row['expected_band'] == row['actual_band'] for row in rows
        ) / max(1, len(rows)), 4),
        'confusion': dict(sorted(confusion.items())),
        'label_note': 'high/medium/low are provisional calibration bands; replace with blinded human scores before changing fusion weights',
    }
    if details:
        output['items'] = rows
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Evaluate deterministic scoring bands.')
    parser.add_argument('--details', action='store_true')
    args = parser.parse_args()
    evaluate(details=args.details)
