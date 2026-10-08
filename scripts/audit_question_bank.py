import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.models import Position, Question  # noqa: E402
from app.services.question_quality_service import (  # noqa: E402
    is_question_interview_ready,
    question_quality_errors,
)


def audit():
    app = create_app()
    has_quality_issues = False
    with app.app_context():
        result = {}
        for position in Position.list_all():
            rows = Question.query.filter_by(
                position_id=position.id,
                is_active=True,
            ).all()
            scoring_issues = []
            quality_issues = []
            for row in rows:
                points = row.get_scoring_points()
                total_weight = sum(
                    float(point.get('weight') or 0)
                    for point in points if isinstance(point, dict)
                )
                if not points or abs(total_weight - 100) > 0.01:
                    scoring_issues.append(row.id)
                errors = question_quality_errors(
                    row.content,
                    row.reference_answer,
                    row.scoring_points,
                    row.type,
                )
                if errors or row.review_status not in ('reviewed', 'ai_reviewed'):
                    quality_issues.append({
                        'id': row.id,
                        'content': row.content,
                        'review_status': row.review_status,
                        'errors': errors,
                    })
            result[position.code] = {
                'total': len(rows),
                'interview_ready': sum(
                    is_question_interview_ready(row) for row in rows
                ),
                'core': sum(bool(row.is_core) for row in rows),
                'review_status': dict(Counter(row.review_status for row in rows)),
                'types': dict(Counter(row.type for row in rows)),
                'difficulty': dict(sorted(Counter(row.difficulty for row in rows).items())),
                'scoring_point_issues': scoring_issues,
                'quality_issues': quality_issues,
            }
            has_quality_issues = has_quality_issues or bool(quality_issues)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if has_quality_issues else 0


if __name__ == '__main__':
    raise SystemExit(audit())
