#!/usr/bin/env python3
"""
build_site.py
Génère toute la structure du site pergola :
- Page d'accueil
- 9 pages piliers
- 67 pages secondaires
- Articles de blog (1 par jour via GitHub Actions)
- Maillage interne automatique
- Sitemap
"""

import os
import json
import re
import random
import urllib.request
import urllib.parse
import anthropic
from datetime import datetime
from pathlib import Path

# ─── CONFIG ───────────────────────────────────────────────
SITE_URL = "https://eolive43.github.io/pergola-guide"
SITE_NOM = "Pergola Guide France"
SITE_LOGO = "🏡 Pergola Guide France"

# ─── CHARGER L'ARCHITECTURE ───────────────────────────────
def charger_architecture():
    with open("architecture.json", encoding="utf-8") as f:
        return json.load(f)

# ─── UNSPLASH ─────────────────────────────────────────────
def recuperer_image(query="pergola jardin"):
    access_key = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    defaut = {
        "url": "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=1200",
        "thumb": "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400",
        "credit_nom": "Unsplash",
        "credit_url": "https://unsplash.com"
    }
    if not access_key:
        return defaut
    try:
        q = urllib.parse.quote(query)
        url = f"https://api.unsplash.com/search/photos?query={q}&per_page=10&orientation=landscape&client_id={access_key}"
        req = urllib.request.Request(url, headers={"Accept-Version": "v1"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            results = data.get("results", [])
            if results:
                photo = random.choice(results[:5])
                return {
                    "url": photo["urls"]["regular"],
                    "thumb": photo["urls"]["small"],
                    "credit_nom": photo["user"]["name"],
                    "credit_url": photo["user"]["links"]["html"] + "?utm_source=pergola_guide&utm_medium=referral"
                }
    except Exception as e:
        print(f"Erreur Unsplash : {e}")
    return defaut

# ─── CLAUDE API ───────────────────────────────────────────
def appeler_claude(prompt, max_tokens=3000):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()

def extraire_balise(texte, balise):
    pattern = f"<{balise}>(.*?)</{balise}>"
    match = re.search(pattern, texte, re.DOTALL)
    return match.group(1).strip() if match else ""

# ─── GÉNÉRATION DE SLUG ───────────────────────────────────
def slugify(texte):
    s = texte.lower()
    for a, b in [('à','a'),('â','a'),('é','e'),('è','e'),('ê','e'),('î','i'),('ô','o'),('ù','u'),('û','u'),('ç','c')]:
        s = s.replace(a, b)
    s = re.sub(r'[^a-z0-9\s-]', '', s)
    s = re.sub(r'\s+', '-', s.strip())
    return re.sub(r'-+', '-', s)[:60]

# ─── CONSTRUCTION DU HEADER / FOOTER ──────────────────────
def construire_header(archi, niveau="racine", pilier_actuel=None):
    """Génère le header avec menu dynamique."""
    menus = ""
    PILIERS_MENU = ["bioclimatique", "bois", "aluminium", "prix", "installation"]
    for p in [p for p in archi["piliers"] if p["id"] in PILIERS_MENU]:
        actif = "active" if pilier_actuel and p["id"] == pilier_actuel else ""
        prefix = "../" if niveau in ["secondaire", "blog"] else ""
        sous_liens = ""
        for s in p["secondaires"]:
            sous_liens += f'<a href="{prefix}secondaires/{p["id"]}/{s["slug"]}.html">{s["titre"]}</a>\n'
        menus += f"""
        <div class="menu-item {actif}">
          <a href="{prefix}piliers/{p['slug']}.html" class="menu-pilier">{p['titre']}</a>
          <div class="sous-menu">{sous_liens}</div>
        </div>"""

    prefix_home = "../" if niveau in ["secondaire", "blog"] else ""
    return f"""<header>
  <div class="container header-inner">
    <a href="{prefix_home}index.html" class="logo">{SITE_LOGO}</a>
    <button class="menu-toggle" onclick="toggleMenu()">☰</button>
    <nav id="main-nav">
      <a href="{prefix_home}index.html">Accueil</a>
      <div class="menu-deroulant">{menus}</div>
      <a href="{prefix_home}blog.html">Blog</a>
    </nav>
  </div>
</header>"""

def construire_footer(niveau="racine"):
    prefix = "../" if niveau in ["secondaire", "blog"] else ""
    return f"""<footer>
  <div class="container">
    <p>© 2025 EOLIZ — {SITE_NOM}</p>
    <p><a href="{prefix}mentions-legales.html">Mentions légales</a> · <a href="{prefix}sitemap.xml">Sitemap</a></p>
  </div>
</footer>"""

# ─── PAGE D'ACCUEIL ───────────────────────────────────────
def generer_accueil(archi):
    print("🏠 Génération page d'accueil...")
    cards_piliers = ""
    for p in archi["piliers"]:
        cards_piliers += f"""
    <a href="piliers/{p['slug']}.html" class="pilier-card">
      <div class="pilier-card-body">
        <h2>{p['titre']}</h2>
        <p>{p['description']}</p>
        <span class="voir-plus">Voir le guide →</span>
      </div>
    </a>"""

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{SITE_NOM} — Guide complet sur les pergolas en France</title>
  <meta name="description" content="Le guide de référence sur les pergolas en France. Prix, matériaux, installation, réglementation : tout ce qu'il faut savoir pour choisir votre pergola.">
  <link rel="canonical" href="{SITE_URL}/index.html">
  <link rel="stylesheet" href="style.css">
</head>
<body>
  {construire_header(archi, "racine")}
  <section class="hero">
    <div class="container">
      <h1>Le guide de référence sur les pergolas en France</h1>
      <p>Prix, matériaux, installation, réglementation : tout ce qu'il faut savoir pour choisir, installer et entretenir votre pergola.</p>
      <a href="blog.html" class="btn-hero">Voir nos derniers articles →</a>
    </div>
  </section>
  <main class="container">
    <h2 class="section-titre">Nos guides thématiques</h2>
    <div class="piliers-grid">{cards_piliers}</div>
    <div id="derniers-articles">
      <h2 class="section-titre">Derniers articles</h2>
      <div class="articles-grid" id="grid-articles"></div>
    </div>
  </main>
  {construire_footer("racine")}
  <script src="main.js"></script>
</body>
</html>"""

    Path("index.html").write_text(html, encoding="utf-8")
    print("✅ index.html")

# ─── PAGE PILIER ──────────────────────────────────────────
def generer_page_pilier(pilier, archi):
    print(f"📌 Pilier : {pilier['titre']}...")
    image = recuperer_image(f"pergola {pilier['id']}")

    prompt = f"""Tu es expert SEO en pergolas en France. Redige une page pilier complete sur : {pilier['titre']}
Mot-cle principal : {pilier['mot_cle']}

Format attendu :
<META>description 155 caracteres max</META>
<H1>titre h1 optimise</H1>
<INTRO>3 phrases d introduction accrocheuses</INTRO>
<CONTENU>
contenu HTML complet avec h2, h3, p, ul. Minimum 1500 mots. Prix en euros. Conseils pratiques pour la France.
Inclure : definition, types, avantages, prix, conseils achat, installation, entretien.
</CONTENU>
<FAQ1Q>question 1</FAQ1Q><FAQ1R>reponse 1</FAQ1R>
<FAQ2Q>question 2</FAQ2Q><FAQ2R>reponse 2</FAQ2R>
<FAQ3Q>question 3</FAQ3Q><FAQ3R>reponse 3</FAQ3R>
<FAQ4Q>question 4</FAQ4Q><FAQ4R>reponse 4</FAQ4R>
<FAQ5Q>question 5</FAQ5Q><FAQ5R>reponse 5</FAQ5R>"""

    texte = appeler_claude(prompt, max_tokens=4000)

    # Liens vers pages secondaires
    liens_secondaires = ""
    for s in pilier["secondaires"]:
        liens_secondaires += f'<a href="../secondaires/{pilier["id"]}/{s["slug"]}.html" class="lien-secondaire">→ {s["titre"]}</a>\n'

    faq_html = ""
    for i in range(1, 6):
        q = extraire_balise(texte, f"FAQ{i}Q")
        r = extraire_balise(texte, f"FAQ{i}R")
        if q:
            faq_html += f'<div class="faq-item"><button class="faq-question">{q}</button><div class="faq-reponse">{r}</div></div>\n'

    h1 = extraire_balise(texte, "H1") or pilier["titre"]
    meta = extraire_balise(texte, "META") or pilier["description"]
    intro = extraire_balise(texte, "INTRO") or ""
    contenu = extraire_balise(texte, "CONTENU") or ""

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{h1} | {SITE_NOM}</title>
  <meta name="description" content="{meta}">
  <link rel="canonical" href="{SITE_URL}/piliers/{pilier['slug']}.html">
  <link rel="stylesheet" href="../style.css">
  <script type="application/ld+json">
  {{"@context":"https://schema.org","@type":"Article","headline":"{h1}","description":"{meta}","image":"{image['url']}","author":{{"@type":"Organization","name":"{SITE_NOM}"}}}}
  </script>
</head>
<body>
  {construire_header(archi, "pilier", pilier['id'])}
  <main class="container page-pilier">
    <nav class="fil-ariane">
      <a href="../index.html">Accueil</a> › <span>{pilier['titre']}</span>
    </nav>
    <div class="pilier-hero">
      <img src="{image['url']}" alt="{h1}" loading="lazy">
      <div class="pilier-hero-content">
        <h1>{h1}</h1>
        <p class="intro">{intro}</p>
      </div>
    </div>
    <div class="page-layout">
      <article class="contenu-principal">
        <div class="article-body">{contenu}</div>
        <div class="faq-section">
          <h2>Questions fréquentes sur {pilier['titre'].lower()}</h2>
          {faq_html}
        </div>
        <div id="articles-blog-pilier">
          <h2>Nos articles sur {pilier['titre'].lower()}</h2>
          <div class="articles-grid" id="grid-blog-{pilier['id']}"></div>
        </div>
      </article>
      <aside class="sidebar">
        <div class="widget">
          <h3>Dans ce guide</h3>
          {liens_secondaires}
        </div>
        <div class="widget" id="widget-recents"></div>
      </aside>
    </div>
    <p class="image-credit">Photo : <a href="{image['credit_url']}" target="_blank" rel="noopener">{image['credit_nom']}</a> sur Unsplash</p>
  </main>
  {construire_footer("pilier")}
  <script>const PILIER_ID = "{pilier['id']}";</script>
  <script src="../main.js"></script>
</body>
</html>"""

    Path(f"piliers/{pilier['slug']}.html").write_text(html, encoding="utf-8")
    print(f"  ✅ piliers/{pilier['slug']}.html")

# ─── PAGE SECONDAIRE ──────────────────────────────────────
def generer_page_secondaire(secondaire, pilier, archi):
    print(f"  📄 Secondaire : {secondaire['titre']}...")
    image = recuperer_image(f"pergola {secondaire['mot_cle']}")

    # Liens vers les autres pages secondaires du même pilier (pages soeurs)
    liens_soeurs = ""
    for s in pilier["secondaires"]:
        if s["slug"] != secondaire["slug"]:
            liens_soeurs += f'<a href="{s["slug"]}.html">→ {s["titre"]}</a>\n'

    prompt = f"""Tu es expert SEO en pergolas en France. Redige une page secondaire complete sur : {secondaire['titre']}
Mot-cle principal : {secondaire['mot_cle']}
Cette page fait partie du guide : {pilier['titre']}

Format attendu :
<META>description 155 caracteres max</META>
<H1>titre h1 optimise</H1>
<INTRO>2-3 phrases d introduction</INTRO>
<CONTENU>
contenu HTML avec h2, h3, p, ul. Minimum 800 mots. Prix en euros. Conseils pratiques France.
</CONTENU>
<FAQ1Q>question 1</FAQ1Q><FAQ1R>reponse 1</FAQ1R>
<FAQ2Q>question 2</FAQ2Q><FAQ2R>reponse 2</FAQ2R>
<FAQ3Q>question 3</FAQ3Q><FAQ3R>reponse 3</FAQ3R>"""

    texte = appeler_claude(prompt, max_tokens=2500)

    faq_html = ""
    for i in range(1, 4):
        q = extraire_balise(texte, f"FAQ{i}Q")
        r = extraire_balise(texte, f"FAQ{i}R")
        if q:
            faq_html += f'<div class="faq-item"><button class="faq-question">{q}</button><div class="faq-reponse">{r}</div></div>\n'

    h1 = extraire_balise(texte, "H1") or secondaire["titre"]
    meta = extraire_balise(texte, "META") or secondaire["titre"]
    intro = extraire_balise(texte, "INTRO") or ""
    contenu = extraire_balise(texte, "CONTENU") or ""

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{h1} | {SITE_NOM}</title>
  <meta name="description" content="{meta}">
  <link rel="canonical" href="{SITE_URL}/secondaires/{pilier['id']}/{secondaire['slug']}.html">
  <link rel="stylesheet" href="../../style.css">
</head>
<body>
  {construire_header(archi, "secondaire", pilier['id'])}
  <main class="container">
    <nav class="fil-ariane">
      <a href="../../index.html">Accueil</a> ›
      <a href="../../piliers/{pilier['slug']}.html">{pilier['titre']}</a> ›
      <span>{secondaire['titre']}</span>
    </nav>
    <div class="page-layout">
      <article class="contenu-principal">
        <img src="{image['url']}" alt="{h1}" class="article-img" loading="lazy">
        <p class="image-credit"><a href="{image['credit_url']}" target="_blank" rel="noopener">{image['credit_nom']}</a> / Unsplash</p>
        <h1>{h1}</h1>
        <p class="intro">{intro}</p>
        <div class="article-body">{contenu}</div>
        <div class="faq-section">
          <h2>Questions fréquentes</h2>
          {faq_html}
        </div>
        <div class="articles-connexes">
          <h2>Articles de blog sur ce sujet</h2>
          <div class="connexes-grid" id="blog-connexes"></div>
        </div>
      </article>
      <aside class="sidebar">
        <div class="widget">
          <h3>Guide {pilier['titre']}</h3>
          <a href="../../piliers/{pilier['slug']}.html">← Retour au guide complet</a>
          <h4 style="margin:12px 0 8px;font-size:0.9rem;color:var(--vert)">Pages du guide</h4>
          {liens_soeurs}
        </div>
      </aside>
    </div>
  </main>
  {construire_footer("secondaire")}
  <script>const PILIER_ID = "{pilier['id']}"; const PAGE_SLUG = "{secondaire['slug']}";</script>
  <script src="../../main.js"></script>
</body>
</html>"""

    Path(f"secondaires/{pilier['id']}/{secondaire['slug']}.html").write_text(html, encoding="utf-8")

# ─── ARTICLE DE BLOG (quotidien) ──────────────────────────
def generer_article_blog(archi):
    # Charger les sujets
    sujets_file = Path("sujets.json")
    if not sujets_file.exists():
        print("❌ sujets.json introuvable")
        return

    with open(sujets_file) as f:
        sujets = json.load(f)

    # Sujets déjà traités
    traites_file = Path("sujets_traites.json")
    traites = json.loads(traites_file.read_text()) if traites_file.exists() else []
    restants = [s for s in sujets if s["slug"] not in traites]
    if not restants:
        traites = []
        restants = sujets

    sujet = random.choice(restants)
    traites.append(sujet["slug"])
    traites_file.write_text(json.dumps(traites, ensure_ascii=False))

    # Trouver le pilier parent
    pilier_parent = None
    secondaire_parent = None
    for p in archi["piliers"]:
        if p["id"] == sujet.get("pilier_id"):
            pilier_parent = p
            for s in p["secondaires"]:
                if s["slug"] == sujet.get("secondaire_slug"):
                    secondaire_parent = s
            break

    image = recuperer_image(f"pergola {sujet.get('mot_cle', 'jardin')}")

    prompt = f"""Tu es expert SEO en pergolas en France. Redige un article de blog sur : {sujet['titre']}
Mot-cle : {sujet['mot_cle']}

Format :
<META>description 155 caracteres</META>
<INTRO>2-3 phrases d accroche</INTRO>
<CONTENU>contenu HTML h2 h3 p ul, 800-1000 mots, prix euros, conseils France</CONTENU>
<FAQ1Q>question</FAQ1Q><FAQ1R>reponse</FAQ1R>
<FAQ2Q>question</FAQ2Q><FAQ2R>reponse</FAQ2R>
<FAQ3Q>question</FAQ3Q><FAQ3R>reponse</FAQ3R>"""

    texte = appeler_claude(prompt, max_tokens=2000)

    meta = extraire_balise(texte, "META") or sujet["titre"]
    intro = extraire_balise(texte, "INTRO") or ""
    contenu = extraire_balise(texte, "CONTENU") or ""
    faq_html = ""
    for i in range(1, 4):
        q = extraire_balise(texte, f"FAQ{i}Q")
        r = extraire_balise(texte, f"FAQ{i}R")
        if q:
            faq_html += f'<div class="faq-item"><button class="faq-question">{q}</button><div class="faq-reponse">{r}</div></div>\n'

    # Liens de maillage interne
    lien_pilier = ""
    lien_secondaire = ""
    if pilier_parent:
        lien_pilier = f'<a href="../../piliers/{pilier_parent["slug"]}.html" class="lien-maillage">📖 Guide complet : {pilier_parent["titre"]}</a>'
    if secondaire_parent:
        lien_secondaire = f'<a href="../../secondaires/{pilier_parent["id"]}/{secondaire_parent["slug"]}.html" class="lien-maillage">→ {secondaire_parent["titre"]}</a>'

    date_iso = datetime.now().strftime("%Y-%m-%d")

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{sujet['titre']} | {SITE_NOM}</title>
  <meta name="description" content="{meta}">
  <link rel="canonical" href="{SITE_URL}/blog/{sujet['slug']}.html">
  <link rel="stylesheet" href="../../style.css">
</head>
<body>
  {construire_header(archi, "blog", sujet.get('pilier_id'))}
  <main class="container">
    <nav class="fil-ariane">
      <a href="../../index.html">Accueil</a> ›
      {"<a href='../../piliers/" + pilier_parent['slug'] + ".html'>" + pilier_parent['titre'] + "</a> ›" if pilier_parent else ""}
      <span>{sujet['titre']}</span>
    </nav>
    <div class="page-layout">
      <article class="contenu-principal">
        <span class="categorie">{sujet.get('categorie', 'Blog')}</span>
        <h1>{sujet['titre']}</h1>
        <p class="intro">{intro}</p>
        <img src="{image['url']}" alt="{sujet['titre']}" class="article-img" loading="lazy">
        <p class="image-credit"><a href="{image['credit_url']}" target="_blank" rel="noopener">{image['credit_nom']}</a> / Unsplash</p>
        <div class="article-body">{contenu}</div>
        <div class="maillage-interne">
          <h3>Pour aller plus loin</h3>
          {lien_pilier}
          {lien_secondaire}
        </div>
        <div class="faq-section">
          <h2>Questions fréquentes</h2>
          {faq_html}
        </div>
      </article>
      <aside class="sidebar">
        <div class="widget" id="widget-recents"></div>
      </aside>
    </div>
  </main>
  {construire_footer("blog")}
  <script>const PILIER_ID = "{sujet.get('pilier_id', '')}";</script>
  <script src="../../main.js"></script>
</body>
</html>"""

    Path(f"blog/{sujet['slug']}.html").write_text(html, encoding="utf-8")

    # Mettre à jour l'index des articles
    index_file = Path("articles.json")
    articles = json.loads(index_file.read_text(encoding="utf-8")) if index_file.exists() else []
    articles.insert(0, {
        "slug": sujet["slug"],
        "titre": sujet["titre"],
        "categorie": sujet.get("categorie", "Blog"),
        "description": meta,
        "date": date_iso,
        "thumb": image["thumb"],
        "pilier_id": sujet.get("pilier_id", ""),
        "secondaire_slug": sujet.get("secondaire_slug", "")
    })
    articles = articles[:500]
    index_file.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")

    generer_page_blog(archi, articles)
    generer_sitemap(archi, articles)
    print(f"✅ blog/{sujet['slug']}.html")

# ─── PAGE BLOG ────────────────────────────────────────────
def generer_page_blog(archi, articles):
    cards = ""
    for art in articles[:50]:
        thumb = art.get("thumb", "")
        img = f'<img src="{thumb}" alt="{art["titre"]}" class="card-image">' if thumb else ""
        cards += f"""
    <a href="blog/{art['slug']}.html" class="article-card">
      {img}
      <div class="card-body">
        <span class="categorie">{art['categorie']}</span>
        <h2>{art['titre']}</h2>
        <p>{art['description'][:100]}...</p>
      </div>
    </a>"""

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Blog Pergola | {SITE_NOM}</title>
  <meta name="description" content="Tous nos articles et conseils sur les pergolas en France.">
  <link rel="stylesheet" href="style.css">
</head>
<body>
  {construire_header(archi, "racine")}
  <main class="container">
    <h1 style="font-family:Georgia,serif;color:var(--vert);padding:40px 0 24px;">Blog & Conseils Pergola</h1>
    <div class="articles-grid">{cards}</div>
  </main>
  {construire_footer("racine")}
  <script src="main.js"></script>
</body>
</html>"""
    Path("blog.html").write_text(html, encoding="utf-8")

# ─── SITEMAP ──────────────────────────────────────────────
def generer_sitemap(archi, articles):
    urls = [f'<url><loc>{SITE_URL}/index.html</loc><priority>1.0</priority><changefreq>daily</changefreq></url>']
    for p in archi["piliers"]:
        urls.append(f'<url><loc>{SITE_URL}/piliers/{p["slug"]}.html</loc><priority>0.9</priority><changefreq>monthly</changefreq></url>')
        for s in p["secondaires"]:
            urls.append(f'<url><loc>{SITE_URL}/secondaires/{p["id"]}/{s["slug"]}.html</loc><priority>0.8</priority><changefreq>monthly</changefreq></url>')
    for art in articles:
        urls.append(f'<url><loc>{SITE_URL}/blog/{art["slug"]}.html</loc><lastmod>{art["date"]}</lastmod><priority>0.6</priority><changefreq>yearly</changefreq></url>')

    sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{''.join(urls)}
</urlset>"""
    Path("sitemap.xml").write_text(sitemap, encoding="utf-8")
    print("✅ sitemap.xml")

# ─── MAIN ─────────────────────────────────────────────────
def main():
    import sys
    archi = charger_architecture()
    mode = sys.argv[1] if len(sys.argv) > 1 else "blog"

    if mode == "full":
        # Construction complète du site (1 seule fois)
        print("🚀 Construction complète du site...")
        Path("piliers").mkdir(exist_ok=True)
        Path("secondaires").mkdir(exist_ok=True)
        Path("blog").mkdir(exist_ok=True)

        generer_accueil(archi)

        for pilier in archi["piliers"]:
            generer_page_pilier(pilier, archi)
            Path(f"secondaires/{pilier['id']}").mkdir(exist_ok=True)
            for secondaire in pilier["secondaires"]:
                generer_page_secondaire(secondaire, pilier, archi)

        articles = json.loads(Path("articles.json").read_text()) if Path("articles.json").exists() else []
        generer_page_blog(archi, articles)
        generer_sitemap(archi, articles)
        print("🎉 Site complet généré !")

    elif mode == "blog":
        # Mode quotidien : 1 article de blog
        print("📝 Génération article quotidien...")
        Path("blog").mkdir(exist_ok=True)
        generer_article_blog(archi)
        print("🎉 Article publié !")

if __name__ == "__main__":
    main()
