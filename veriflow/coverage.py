"""Evidence coverage for the existing authenticated private dashboard."""
import html
from .admin import table
from .strategy import RESEARCH_MIN_TEXT_REVIEWS


def render(conn, params, csrf):
    totals = conn.execute('''SELECT count(*) AS distinct_software_products,
      count(*) FILTER(WHERE reviews>=1) AS products_with_1_plus_reviews,
      count(*) FILTER(WHERE reviews>=3) AS products_with_3_plus_reviews,
      count(*) FILTER(WHERE reviews>=5) AS products_with_5_plus_reviews,
      count(*) FILTER(WHERE reviews>=10) AS products_with_10_plus_reviews,
      count(*) FILTER(WHERE text_reviews<%s) AS products_lacking_research_evidence,
      count(*) FILTER(WHERE text_reviews>=%s) AS ready_for_deeper_research,
      count(*) FILTER(WHERE research_requested_at IS NOT NULL AND reviews>0) AS selected_for_editorial_research
      FROM veriflow.product_evidence''',
      (RESEARCH_MIN_TEXT_REVIEWS,RESEARCH_MIN_TEXT_REVIEWS)).fetchone()
    categories = conn.execute('''SELECT c.name AS software_category,
      count(DISTINCT e.product_id) AS products,
      count(DISTINCT e.product_id) FILTER(WHERE e.reviews>0) AS products_with_evidence
      FROM veriflow.categories c JOIN veriflow.product_categories pc ON pc.category_id=c.id
      JOIN veriflow.products p ON p.id=pc.product_id
      JOIN veriflow.product_evidence e ON e.product_id=coalesce(p.canonical_product_id,p.id)
      GROUP BY c.id ORDER BY products_with_evidence,c.name''').fetchall()
    totals['software_categories_covered'] = sum(r['products_with_evidence']>0 for r in categories)
    totals['unclassified_products'] = conn.execute('''SELECT count(*) AS n
      FROM veriflow.product_evidence e WHERE NOT EXISTS(
        SELECT 1 FROM veriflow.products p JOIN veriflow.product_categories pc ON pc.product_id=p.id
        WHERE coalesce(p.canonical_product_id,p.id)=e.product_id)''').fetchone()['n']
    q = params.get('q',[''])[0][:200]
    raw_filter = params.get('evidence',['all'])[0]
    filters = {'all':'true','none':'e.reviews=0','insufficient':'e.text_reviews<3',
               'ready':'e.text_reviews>=3','queued':'e.research_requested_at IS NOT NULL AND e.reviews>0'}
    condition = filters.get(raw_filter,'true')
    rows = conn.execute(f'''SELECT e.product_id,e.name,e.reviews AS authentic_reviews,
      e.text_reviews,e.independent_sources,
      CASE WHEN e.reviews=0 THEN 'No evidence — research blocked'
           WHEN e.text_reviews<3 THEN 'Limited evidence — not research-ready'
           ELSE 'Ready for deeper manual research — not publication' END AS evidence_status,
      e.research_requested_at,
      (SELECT string_agg(DISTINCT c.name,', ' ORDER BY c.name)
       FROM veriflow.products p JOIN veriflow.product_categories pc ON pc.product_id=p.id
       JOIN veriflow.categories c ON c.id=pc.category_id
       WHERE coalesce(p.canonical_product_id,p.id)=e.product_id) AS software_categories
      FROM veriflow.product_evidence e WHERE e.name ILIKE %s AND {condition}
      ORDER BY e.reviews,e.name LIMIT 100''', ('%'+q+'%',)).fetchall()
    options = ''.join('<option value="'+html.escape(str(p['product_id']),quote=True)+'">'
                      +html.escape(p['name'])+'</option>' for p in
                      conn.execute('SELECT product_id,name FROM veriflow.product_evidence '
                                   'ORDER BY name').fetchall())
    evidence_options = ''.join('<option value="'+html.escape(str(p['product_id']),quote=True)+'">'
                      +html.escape(p['name'])+'</option>' for p in
                      conn.execute('SELECT product_id,name FROM veriflow.product_evidence '
                                   'WHERE reviews>0 ORDER BY name').fetchall())
    hidden = '<input type="hidden" name="csrf" value="'+html.escape(csrf,quote=True)+'">'
    controls = (
        '<p><strong>Default: Breadth First, 5 unique reviews per product.</strong> '
        'Targets are collection priorities, not storage caps. Balanced defaults to 10; Depth First to 30. '
        'Existing batches keep their original strategy and limits.</p>'
        '<p>Evidence requires successful recorded ingestion, a non-revoked authorization, '
        'a source link and required attribution/license. Expired collection windows do not erase '
        'continuing reuse rights. Counts are not independent verification of customer claims.</p>'
        +table([{'metric':k.replace('_',' '),'count':v} for k,v in totals.items()])
        +'<h3>Software category coverage</h3>'+table(categories)
        +'<h3>Editorial research only</h3><p>Three full-text reviews is a planning threshold for '
        'deeper manual research, not a quality guarantee or permission to publish. '
        'One review may be selected for investigation with a limited-evidence warning. '
        'No article generation or publishing is enabled. Recheck original reviews before making claims.</p>'
        +'<form method="post" action="/research/queue">'+hidden
        +'<select name="product_id" required>'+evidence_options+'</select>'
        +'<button>Select for manual editorial research</button></form>'
        +'<details><summary>Correct a duplicate product identity</summary>'
        '<p>Only confirm the same software product, not competitors or products sharing a hosting domain. '
        'This groups evidence without deleting or moving reviews. Active products cannot be linked.</p>'
        '<form method="post" action="/products/identity">'+hidden
        +'<label>Duplicate name <select name="product_id">'+options+'</select></label>'
        +'<label>Keep canonical identity <select name="canonical_id">'+options+'</select></label>'
        +'<button>Confirm same product</button></form></details>'
        +'<h3>Product evidence</h3><form><input name="q" placeholder="Find software" value="'
        +html.escape(q,quote=True)+'"><select name="evidence">'
        +''.join('<option value="'+key+'"'+(' selected' if raw_filter==key else '')+'>'
                 +label+'</option>' for key,label in (
                     ('all','All products'),('none','No evidence'),('insufficient','Insufficient evidence'),
                     ('ready','Ready for deeper research'),('queued','Selected research')))
        +'</select><button>Filter</button></form>'
        '<p>Up to 100 matching products, least-covered first. Independent sources are distinct '
        'source hostnames, not numbers of imports or reviews. Shared ownership across different '
        'domains still requires manual verification. Reload to see newly ingested evidence.</p>')
    return controls, rows
