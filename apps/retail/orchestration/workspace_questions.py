"""Transparent evidence lookup, with optional local language-model explanations."""
import re
import streamlit as st


def answer_question(question, run=None):
    q = question.lower().strip()
    if any(w in q for w in ('upload', 'column', 'template', 'file', 'feed')):
        return ('Upload Vendor onboarding, Item onboarding, and Purchase orders in the Decision workspace. Use the Catalog file from the certified cycle pack; '
                'the earlier item_onboarding_400_rows.xlsx contains the same rows, so do not upload both. '
                'Item onboarding needs sku, vendor_id, product_name, category and price. Keep gtin as text; '
                'include brand, description, image_url, colour, size, material and vendor_approved for the quality checks. '
                'Vendor IDs must exist in Vendor, and PO SKUs and vendor IDs must match the Item onboarding file. '
                'Supply currency, cost and quantity on every PO line. After correcting a file, replace it and click Run checks again.')
    if not run:
        return 'Run your three files first so I can answer from their results. You can ask about upload columns now.'
    prefix = f"Run {run['orchestration_run_id']}: {run['decision']} ({run['status']}). "
    values = list(run['assessments'].values())
    if any(w in q for w in ('approve', 'release', 'ready', 'status', 'summary')):
        return prefix + run['decision_detail']['rationale'] + ' Review approval is recorded only through the approval control.'
    if any(w in q for w in ('how many', 'count', 'total')):
        return prefix + '\n\n' + '\n'.join(f"{a['label']}: {a['total_records']} assessed, {a['blocked_records']} blocked, {a['warning_records']} warnings." for a in values) + '\nOnboarding includes vendors and items; do not add these domain totals together as unique records.'
    tokens = set(re.findall(r'[a-z0-9_-]{3,}', q)) - {'the', 'what', 'why', 'are', 'for', 'this', 'can', 'you', 'how', 'and', 'with', 'please'}
    identifiers = set(re.findall(r'\b(?:sku|vnd|po)-[a-z0-9_-]+', q))
    matches = []
    for a in values:
        for f in a['findings']:
            if not identifiers and str(f.get('Status', '')).upper() in {'READY', 'NONE'}:
                continue
            text = ' '.join(str(v) for v in f.values())
            hit = bool(identifiers.intersection(set(re.findall(r'[a-z0-9_-]{3,}', text.lower())))) if identifiers else (tokens.intersection(set(re.findall(r'[a-z0-9_-]{3,}', text.lower()))) or any(w in q for w in ('block', 'next', 'fix', 'error', 'issue')))
            if hit:
                matches.append(f"{a['label']} — {f.get('Identifier', '')}: {f.get('Issue', '')}. {f.get('Action', '')}")
    matches = list(dict.fromkeys(matches))
    if matches:
        return prefix + '\n\n' + '\n\n'.join(matches[:5]) + f'\n\nShowing up to five matching findings. Full findings are in Details & downloads.'
    return prefix + 'I cannot answer that from the available evidence. Try a SKU/vendor ID, “What is blocked?”, “How many warnings?”, or “Which upload columns do I need?”'


def render_questions(run=None, key='workspace'):
    st.subheader('Ask about your data')
    st.caption('Type a question about blockers, counts, a SKU, or the upload format. Evidence lookup works without an AI service.')
    with st.form(key + '_question_form'):
        question = st.text_input('Your question', placeholder='Why is SKU-SCALE-0001 blocked?', max_chars=1000)
        ask = st.form_submit_button('Ask')
    if ask and question.strip():
        st.caption('Evidence lookup — rule-based, not a general AI chat.')
        st.write(answer_question(question, run))
