import hashlib
import io
import re
from pathlib import Path

from app import db
from app.models import Knowledge


ALLOWED_EXTENSIONS = {'.md', '.txt', '.pdf'}
MAX_DOCUMENT_BYTES = 5_000_000
MAX_PDF_PAGES = 100
MAX_CHUNKS = 200
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


class KnowledgeImportError(ValueError):
    pass


def _decode_text(data):
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise KnowledgeImportError('文本编码无法识别，请使用 UTF-8 文件')


def extract_document_text(data, filename):
    suffix = Path(filename or '').suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise KnowledgeImportError('仅支持 Markdown、TXT 和 PDF 文件')
    if not data:
        raise KnowledgeImportError('导入文件为空')
    if len(data) > MAX_DOCUMENT_BYTES:
        raise KnowledgeImportError('导入文件不能超过 5 MB')
    if suffix in {'.md', '.txt'}:
        text = _decode_text(data)
    else:
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise KnowledgeImportError('不支持加密 PDF')
            if len(reader.pages) > MAX_PDF_PAGES:
                raise KnowledgeImportError('PDF 不能超过 100 页')
            text = '\n\n'.join((page.extract_text() or '') for page in reader.pages)
        except KnowledgeImportError:
            raise
        except Exception as error:
            raise KnowledgeImportError('PDF 无法解析或未包含可提取文本') from error
    text = text.replace('\x00', '').replace('\r\n', '\n').strip()
    if len(re.sub(r'\s+', '', text)) < 20:
        raise KnowledgeImportError('文件中可用文本过少，扫描版 PDF 请先完成 OCR')
    return text


def split_document(text, filename):
    base_title = Path(filename).stem[:180] or '导入知识'
    sections = []
    heading = base_title
    paragraphs = []
    for line in text.splitlines():
        heading_match = re.match(r'^\s{0,3}#{1,6}\s+(.+?)\s*$', line)
        if heading_match:
            if paragraphs:
                sections.append((heading, '\n'.join(paragraphs).strip()))
                paragraphs = []
            heading = heading_match.group(1).strip()[:180]
        else:
            paragraphs.append(line)
    if paragraphs:
        sections.append((heading, '\n'.join(paragraphs).strip()))
    if not sections:
        sections = [(base_title, text)]

    chunks = []
    for section_title, section_text in sections:
        compact = re.sub(r'\n{3,}', '\n\n', section_text).strip()
        start = 0
        while start < len(compact):
            end = min(len(compact), start + CHUNK_SIZE)
            if end < len(compact):
                boundary = max(
                    compact.rfind('\n', start + CHUNK_SIZE // 2, end),
                    compact.rfind('。', start + CHUNK_SIZE // 2, end),
                )
                if boundary > start:
                    end = boundary + 1
            content = compact[start:end].strip()
            if content:
                chunks.append((section_title, content))
            if end >= len(compact):
                break
            start = max(start + 1, end - CHUNK_OVERLAP)
            if len(chunks) >= MAX_CHUNKS:
                raise KnowledgeImportError('文档分块超过 200 条，请拆分文件后再导入')
    return chunks


def import_document(data, filename, position_code, source='document_import'):
    text = extract_document_text(data, filename)
    chunks = split_document(text, filename)
    created = 0
    skipped = 0
    for index, (section_title, content) in enumerate(chunks):
        source_hash = hashlib.sha256(
            f'{position_code}\0{content}'.encode('utf-8')
        ).hexdigest()
        exists = Knowledge.query.filter_by(
            position_code=position_code,
            source_hash=source_hash,
        ).first()
        if exists:
            skipped += 1
            continue
        title = section_title if len(chunks) == 1 else f'{section_title} [{index + 1}]'
        db.session.add(Knowledge(
            position_code=position_code,
            title=title[:256],
            content=content,
            topic=section_title[:128],
            source=(source or 'document_import')[:128],
            document_name=(filename or '')[:256],
            chunk_index=index,
            source_hash=source_hash,
        ))
        created += 1
    db.session.commit()
    return {
        'created': created,
        'skipped_duplicates': skipped,
        'total_chunks': len(chunks),
        'document_name': filename,
    }
