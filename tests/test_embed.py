import json

from hydra.embed import extract_embedded, _harvest_records, _extract_json_at


def test_next_data_extraction():
    data = {"props": {"pageProps": {"apolloState": {"data": {
        "Job:1": {"title": "ML Eng", "company": "Acme"},
        "Job:2": {"title": "Backend", "company": "Beta"},
        "Job:3": {"title": "SRE", "company": "Gamma"},
        "Job:4": {"title": "FE", "company": "Delta"},
    }}}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    blobs = extract_embedded(html)
    assert blobs and blobs[0].kind == "__NEXT_DATA__"
    assert blobs[0].records_count == 4


def test_rsc_stream_extraction_picks_content_over_taxonomy():
    # two record shapes in the stream: a big taxonomy (no content keys) and items
    # (with price/photo). The content-scored cluster must win, not the bigger one.
    cats = ",".join(f'{{"id":{i},"code":"C{i}","title":"cat","url":"/c"}}'
                    for i in range(50))
    items = ",".join(f'{{"content_source":"search","id":{i},"title":"Nike",'
                     f'"price":{{"amount":"7"}},"photo":{{"url":"x"}},"url":"/items/{i}"}}'
                     for i in range(8))
    stream = f'[{cats},{items}]'
    html = 'self.__next_f.push([1,' + json.dumps(stream) + '])'
    blobs = extract_embedded(html)
    rsc = [b for b in blobs if b.kind == "__next_f (RSC)"]
    assert rsc, "RSC blob should be found"
    assert "price" in rsc[0].sample                          # item, not category


def test_extract_json_at_is_string_aware():
    # a brace inside a string value must not end the object early
    text = 'x{"name":"a}b","id":1}y'
    frag = _extract_json_at(text, text.index("{"))
    assert json.loads(frag) == {"name": "a}b", "id": 1}


def test_next_data_prefers_product_over_bigger_config():
    # the StockX/Home Depot bug: a big config array must NOT beat the smaller
    # content-rich product list. Content-key scoring should pick the product.
    data = {"props": {"pageProps": {
        "appConfig": {f"S{i}": {"DOMAIN": "x", "CLIENTID": "y"} for i in range(30)},
        "offers": [{"sku": f"s{i}", "price": 280 + i, "availability": "InStock"}
                   for i in range(6)],
    }}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    b = extract_embedded(html)[0]
    assert "price" in b.sample                       # product, not config
    assert b.records_count == 6


def test_price_record_beats_numerous_reviews():
    # the Home Depot case: a single price-bearing product must outrank a bigger
    # reviews list (reviews are content-ish but carry no money keys).
    prod = {"@graph": [{"@type": "Product", "name": "Fan",
                        "offers": {"price": 89, "availability": "InStock", "sku": "X"}}]}
    revs = {"review": [{"author": "a", "rating": 5, "reviewBody": "ok", "description": "x"}
                       for _ in range(10)]}
    html = (f'<script type="application/ld+json">{json.dumps(prod)}</script>'
            f'<script type="application/ld+json">{json.dumps(revs)}</script>')
    top = extract_embedded(html)[0].sample
    assert "offers" in top or "price" in json.dumps(top)   # product, not reviews


def test_ldjson_extraction():
    html = ('<script type="application/ld+json">'
            '{"mainEntity":[{"@type":"Q","name":"one"},{"@type":"Q","name":"two"}]}'
            '</script>')
    blobs = extract_embedded(html)
    assert any(b.kind == "ld+json" for b in blobs)
