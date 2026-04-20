#!/usr/bin/env python3
"""
build_site.py — Version finale complète
Améliorations :
- Replicate FLUX.1-dev (piliers) / FLUX.1-schnell (secondaires+blog)
- 2 images sur piliers, 1 sur secondaires+blog, toutes 1200px
- meta robots max-image-preview:large (Google Discover)
- Schemas JSON-LD : FAQPage, BreadcrumbList, HowTo, Article enrichi
- datePublished+dateModified blog, dateModified piliers/secondaires
- Prompts SEO boostés + keywords.json
- Titres blog Discover-friendly
- Maillage statique HTML bidirectionnel
- Liens contextuels dans le corps du texte
- Ancres diversifiées depuis comments_config.json
- Articles similaires en bas des billets
- Ping Google sitemap après publication

URL structure (v2) :
- Accueil         : /index.html
- Pilier          : /{pilier-slug}.html             ex: /pergola-aluminium.html
- Secondaire      : /{pilier-id}/{slug}.html        ex: /aluminium/pergola-aluminium-6x4.html
- Blog            : /blog/{slug}.html
"""

import os, json, re, random, time, urllib.request, urllib.parse
import anthropic
from datetime import datetime
from pathlib import Path

# ─── CONFIG ───────────────────────────────────────────────
SITE_URL = "https://www.pergola-guide.fr"
SITE_NOM  = "Pergola Guide"
SITE_LOGO = "🏡 Guide Pergola"

# ─── CONFIG ADSENSE ───────────────────────────────────────
# Pour activer AdSense le moment venu :
# 1. Passer ADSENSE_ACTIF = True
# 2. Remplacer ADSENSE_CLIENT par ton vrai ID (ca-pub-XXXXXXXXXXXXXXXX)
# 3. Remplacer chaque ADSENSE_SLOT_xxx par tes vrais IDs de blocs AdSense
# 4. Relancer le workflow GitHub Actions en mode "full"
ADSENSE_ACTIF        = False
ADSENSE_CLIENT       = "ca-pub-XXXXXXXXXXXXXXXX"
ADSENSE_SLOT_HAUT    = "1111111111"   # Bloc horizontal haut (responsive)
ADSENSE_SLOT_MILIEU  = "2222222222"   # Bloc in-article (milieu contenu)
ADSENSE_SLOT_BAS     = "3333333333"   # Bloc horizontal bas (avant commentaires)
ADSENSE_SLOT_SIDEBAR = "4444444444"   # Bloc sidebar (300x250)

def script_adsense_head():
    """Script AdSense dans le <head> — vide si inactif."""
    if not ADSENSE_ACTIF:
        return "<!-- AdSense : inactif pour l'instant -->"
    return (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/' 
            f'adsbygoogle.js?client={ADSENSE_CLIENT}" crossorigin="anonymous"></script>')

def bloc_adsense(slot_id, type_bloc="inArticle"):
    """
    Génère un emplacement publicitaire AdSense.
    Inactif  → div vide avec commentaire (invisible, aucun impact perf)
    Actif    → vrai bloc AdSense responsive
    type_bloc: 'inArticle' | 'horizontal' | 'sidebar'
    """
    if not ADSENSE_ACTIF:
        return (f'\n<!-- [ADSENSE-{type_bloc.upper()}] Emplacement réservé -->\n'
                f'<div class="adsense-bloc adsense-{type_bloc}" aria-hidden="true"></div>\n')
    return f"""
<div class="adsense-bloc adsense-{type_bloc}">
  <ins class="adsbygoogle"
       style="display:block"
       data-ad-client="{ADSENSE_CLIENT}"
       data-ad-slot="{slot_id}"
       data-ad-format="auto"
       data-full-width-responsive="true"></ins>
  <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
</div>"""


# ─── CHARGEMENT DONNÉES ───────────────────────────────────
def charger_architecture():
    with open("architecture.json", encoding="utf-8") as f:
        return json.load(f)

def charger_keywords():
    p = Path("keywords.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

def charger_comments_config():
    p = Path("comments_config.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

def charger_articles():
    p = Path("articles.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []

# ─── ANCRES DIVERSIFIÉES ──────────────────────────────────
def ancre_aleatoire(pilier_id, comments_config):
    anchres = comments_config.get("anchres_piliers", {})
    liste = anchres.get(pilier_id, [pilier_id])
    return random.choice(liste)

# ─── KEYWORDS PROMPT ──────────────────────────────────────
def formater_keywords_prompt(pilier_id, keywords):
    if pilier_id not in keywords:
        return ""
    data = keywords[pilier_id]
    top_sec = data.get("secondaires", [])[:15]
    top_lt  = data.get("longue_traine", [])[:10]
    lignes  = ["\n=== DONNÉES SEO RÉELLES (Ahrefs France) ==="]
    lignes.append(f"Mot-clé principal : {data['principal']} ({data['volume_principal']:,} recherches/mois)")
    lignes.append("\nMots-clés secondaires à intégrer naturellement :")
    for kw in top_sec:
        lignes.append(f"  - {kw['kw']} ({kw['vol']:,}/mois, intent: {kw['intent']})")
    lignes.append("\nLongue traîne à couvrir dans H2/H3 :")
    for kw in top_lt:
        lignes.append(f"  - {kw['kw']} ({kw['vol']:,}/mois)")
    lignes.append("\nINSTRUCTIONS SEO OBLIGATOIRES :")
    lignes.append("- Mot-clé principal dans H1, 100 premiers mots, et 3+ fois dans le corps")
    lignes.append("- Chaque mot-clé secondaire apparaît au moins 1 fois naturellement")
    lignes.append("- Longue traîne en H2, H3 ou dans les paragraphes")
    lignes.append("- Structure : 1 H1, 5-7 H2, H3 sous chaque H2, listes <ul>")
    lignes.append("- Densité mot-clé principal : 1-2%")
    lignes.append("===========================================\n")
    return "\n".join(lignes)

# ─── REPLICATE IMAGE ──────────────────────────────────────
def generer_image_replicate(prompt_sujet, modele="schnell", largeur=1200, hauteur=800):
    """Génère une image via Replicate FLUX. modele='dev' ou 'schnell'."""
    api_key = os.environ.get("REPLICATE_API_KEY", "")
    if not api_key:
        return None
    
    model_id = (
        "black-forest-labs/flux-1.1-pro" if modele == "dev"
        else "black-forest-labs/flux-schnell"
    )
    
    prompt = (
        f"Photorealistic {prompt_sujet}, beautiful French garden terrace, "
        f"sunny natural light, architectural photography, wide angle, "
        f"high quality, sharp details, no people, 16:9"
    )
    
    try:
        # Créer la prédiction
        payload = json.dumps({
            "version": model_id,
            "input": {
                "prompt": prompt,
                "width": largeur,
                "height": hauteur,
                "num_outputs": 1,
                "output_format": "webp",
                "output_quality": 85,
            }
        }).encode()
        
        req = urllib.request.Request(
            "https://api.replicate.com/v1/predictions",
            data=payload,
            headers={
                "Authorization": f"Token {api_key}",
                "Content-Type": "application/json"
            }
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            prediction = json.loads(r.read().decode())
        
        pred_id = prediction.get("id")
        if not pred_id:
            return None
        
        # Poller jusqu'à completion (max 120s)
        for _ in range(60):
            time.sleep(2)
            poll_req = urllib.request.Request(
                f"https://api.replicate.com/v1/predictions/{pred_id}",
                headers={"Authorization": f"Token {api_key}"}
            )
            with urllib.request.urlopen(poll_req, timeout=15) as r:
                result = json.loads(r.read().decode())
            
            status = result.get("status")
            if status == "succeeded":
                output = result.get("output", [])
                if output:
                    return {
                        "url": output[0] if isinstance(output, list) else output,
                        "credit_nom": "IA Generée",
                        "credit_url": "#"
                    }
                break
            elif status in ("failed", "canceled"):
                print(f"  ⚠️ Replicate {status}: {result.get('error')}")
                break
    
    except Exception as e:
        print(f"  ⚠️ Erreur Replicate: {e}")
    
    return None

def recuperer_image_unsplash(query="pergola jardin"):
    """Fallback Unsplash avec images 1200px."""
    access_key = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    defaut = {
        "url": "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=1200",
        "credit_nom": "Unsplash",
        "credit_url": "https://unsplash.com"
    }
    if not access_key:
        return defaut
    try:
        q   = urllib.parse.quote(query)
        url = (f"https://api.unsplash.com/search/photos"
               f"?query={q}&per_page=10&orientation=landscape&client_id={access_key}")
        req = urllib.request.Request(url, headers={"Accept-Version": "v1"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        results = data.get("results", [])
        if results:
            photo = random.choice(results[:5])
            # Force 1200px
            img_url = re.sub(r'w=\d+', 'w=1200', photo["urls"]["regular"])
            return {
                "url": img_url,
                "credit_nom": photo["user"]["name"],
                "credit_url": photo["user"]["links"]["html"] + "?utm_source=pergola_guide&utm_medium=referral"
            }
    except Exception as e:
        print(f"  ⚠️ Erreur Unsplash: {e}")
    return defaut

def get_image(sujet, modele="schnell", chemin_local=None):
    """Essaie Replicate, fallback Unsplash.

    Si chemin_local est fourni (ex: "images/piliers/pergola-bois-1.webp"),
    l'image est téléchargée dans le repo et l'URL renvoyée pointe vers
    le chemin local absolu (ex: "/images/piliers/pergola-bois-1.webp").
    Cela évite que les URLs Replicate temporaires expirent après 24-48h.
    """
    # Si l'image existe déjà en local, on la réutilise (cache parfait)
    if chemin_local:
        p = Path(chemin_local)
        if p.exists() and p.stat().st_size > 5000:  # fichier non vide
            print(f"  ♻️ Image réutilisée : {chemin_local}")
            return {"url": f"/{chemin_local}", "credit_nom": "IA", "credit_url": "#"}

    img = generer_image_replicate(sujet, modele)
    source = "flux"
    if not img:
        print(f"  📷 Fallback Unsplash")
        img = recuperer_image_unsplash(sujet)
        source = "unsplash"
    else:
        print(f"  🎨 Image FLUX générée")

    # Téléchargement vers le repo si demandé
    if chemin_local and img and img.get("url"):
        if telecharger_image(img["url"], chemin_local):
            # Remplacer l'URL temporaire par le chemin local absolu
            img["url"] = f"/{chemin_local}"
            print(f"  💾 Enregistrée : /{chemin_local} ({source})")
        else:
            print(f"  ⚠️ Échec téléchargement vers {chemin_local} — URL externe conservée")

    return img

def telecharger_image(url, chemin_local, timeout=30):
    """Télécharge une image depuis une URL distante vers un chemin local.
    Crée les dossiers parents si nécessaire. Retourne True en cas de succès.
    """
    try:
        p = Path(chemin_local)
        p.parent.mkdir(parents=True, exist_ok=True)

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()

        if len(data) < 5000:  # trop petit = probablement une erreur
            print(f"  ⚠️ Image suspecte (taille {len(data)}o) : {url[:80]}")
            return False

        p.write_bytes(data)
        return True
    except Exception as e:
        print(f"  ⚠️ Erreur téléchargement image : {e}")
        return False

# ─── CLAUDE API ───────────────────────────────────────────
def appeler_claude(prompt, max_tokens=3000):
    client  = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()

def extraire_balise(texte, balise):
    match = re.search(f"<{balise}>(.*?)</{balise}>", texte, re.DOTALL)
    return match.group(1).strip() if match else ""

def slugify(texte):
    s = texte.lower()
    for a, b in [('à','a'),('â','a'),('é','e'),('è','e'),('ê','e'),
                 ('î','i'),('ô','o'),('ù','u'),('û','u'),('ç','c')]:
        s = s.replace(a, b)
    s = re.sub(r'[^a-z0-9\s-]', '', s)
    s = re.sub(r'\s+', '-', s.strip())
    return re.sub(r'-+', '-', s)[:60]

# ─── SCHEMAS JSON-LD ──────────────────────────────────────
def schema_breadcrumb(items):
    """items = [{"name": "Accueil", "url": "..."}, ...]"""
    elements = []
    for i, item in enumerate(items, 1):
        elements.append({
            "@type": "ListItem",
            "position": i,
            "name": item["name"],
            "item": item["url"]
        })
    return json.dumps({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": elements
    }, ensure_ascii=False)

def schema_faq(questions_reponses):
    """questions_reponses = [{"q": "...", "r": "..."}, ...]"""
    if not questions_reponses:
        return ""
    return json.dumps({
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": qr["q"],
                "acceptedAnswer": {"@type": "Answer", "text": qr["r"]}
            }
            for qr in questions_reponses
        ]
    }, ensure_ascii=False)

def schema_article(h1, meta, image_url, date_published=None, date_modified=None, word_count=None):
    data = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": h1,
        "description": meta,
        "image": image_url,
        "author": {"@type": "Organization", "name": SITE_NOM},
        "publisher": {
            "@type": "Organization",
            "name": SITE_NOM,
            "logo": {"@type": "ImageObject", "url": f"{SITE_URL}/logo.png"}
        },
        "inLanguage": "fr",
    }
    if date_published:
        data["datePublished"] = date_published
    if date_modified:
        data["dateModified"] = date_modified
    if word_count:
        data["wordCount"] = word_count
    return json.dumps(data, ensure_ascii=False)

def schema_howto(titre, etapes):
    """Pour pages installation."""
    return json.dumps({
        "@context": "https://schema.org",
        "@type": "HowTo",
        "name": titre,
        "step": [
            {"@type": "HowToStep", "name": e["nom"], "text": e["texte"]}
            for e in etapes
        ]
    }, ensure_ascii=False)

# ─── ARTICLES SIMILAIRES ──────────────────────────────────
def generer_articles_similaires(slug_actuel, pilier_id, articles, n=3):
    """Retourne HTML statique des articles similaires. Liens absolus."""
    similaires = [
        a for a in articles
        if a.get("pilier_id") == pilier_id and a.get("slug") != slug_actuel
    ][:n]
    
    if not similaires:
        return ""
    
    html = '<div class="articles-similaires"><h2>Articles similaires</h2><div class="similaires-grid">'
    for art in similaires:
        thumb = art.get("thumb", "")
        img   = f'<img src="{thumb}" alt="{art["titre"]}" loading="lazy">' if thumb else ""
        html += f"""
        <a href="/blog/{art['slug']}.html" class="similaire-card">
            {img}
            <div class="similaire-body">
                <span class="categorie">{art.get('categorie','Blog')}</span>
                <h3>{art['titre']}</h3>
                <p>{art.get('description','')[:80]}...</p>
            </div>
        </a>"""
    html += '</div></div>'
    return html

# ─── MAILLAGE BLOG → SECONDAIRES (statique) ───────────────
def generer_liens_blog_sur_secondaire(pilier_id, secondaire_slug, articles, n=3):
    """Articles liés affichés en HTML statique sur la page secondaire. Liens absolus."""
    lies = [
        a for a in articles
        if a.get("pilier_id") == pilier_id
        and secondaire_slug in a.get("secondaire_slug", "")
    ][:n]
    
    if not lies:
        # Fallback : articles du même pilier
        lies = [a for a in articles if a.get("pilier_id") == pilier_id][:n]
    
    if not lies:
        return ""
    
    html = '<div class="connexes-grid">'
    for art in lies:
        description = art.get("description", "")[:100]
        html += f"""
        <p>Notre article sur 
        <a href="/blog/{art['slug']}.html">{art['titre']}</a>
        — {description}...</p>"""
    html += '</div>'
    return html

# ─── HEADER / FOOTER ──────────────────────────────────────
# Les liens de navigation utilisent des CHEMINS ABSOLUS (commençant par /).
# C'est le standard sur GitHub Pages avec domaine custom : la racine "/" pointe
# toujours vers la racine du site, peu importe la profondeur de la page courante.
# Cela évite tous les bugs de chemins relatifs (../../) qui cassent à la moindre
# modification de structure.
def construire_header(archi, niveau="racine", pilier_actuel=None):
    """Construit le header avec des liens absolus (robustes quelle que soit la profondeur)."""
    menus = ""
    PILIERS_MENU = ["bioclimatique", "bois", "aluminium", "prix", "installation"]
    for p in [p for p in archi["piliers"] if p["id"] in PILIERS_MENU]:
        actif = "active" if pilier_actuel and p["id"] == pilier_actuel else ""
        # Chemins absolus — valides depuis n'importe quelle profondeur
        lien_pilier = f"/{p['slug']}.html"

        sous_liens = "".join(
            f'<a href="/{p["id"]}/{s["slug"]}.html">{s["titre"]}</a>\n'
            for s in p["secondaires"]
        )
        menus += f"""
        <div class="menu-item {actif}">
          <a href="{lien_pilier}" class="menu-pilier">{p['titre']}</a>
          <div class="sous-menu">{sous_liens}</div>
        </div>"""

    return f"""<header>
  <div class="container header-inner">
    <a href="/" class="logo">{SITE_LOGO}</a>
    <button class="menu-toggle" onclick="toggleMenu()">☰</button>
    <nav id="main-nav">
      <a href="/">Accueil</a>
      <div class="menu-deroulant">{menus}</div>
      <a href="/blog.html">Blog</a>
    </nav>
  </div>
</header>"""

def construire_footer(niveau="racine"):
    """Footer avec liens absolus."""
    return f"""<footer>
  <div class="container">
    <p>© 2025 EOLIZ — {SITE_NOM}</p>
    <p><a href="/mentions-legales.html">Mentions légales</a></p>
  </div>
</footer>"""

def meta_commune():
    """Balises meta communes à toutes les pages."""
    return '<meta name="robots" content="max-image-preview:large">\n  ' + script_adsense_head()

# ─── CHEMINS CSS / JS ─────────────────────────────────────
# Avec des liens absolus pour les assets, plus besoin de gérer la profondeur.
def lien_css():
    return '<link rel="stylesheet" href="/style.css">'

def lien_js():
    return '<script src="/main.js"></script>'

# ─── PAGE D'ACCUEIL ───────────────────────────────────────
def generer_accueil(archi, articles=None, regenerer_images=False):
    """Page d'accueil avec slider, intro fixe, encarts AdSense et derniers articles statiques.

    regenerer_images=True  : force la régénération des 3 images du slider (mode full)
    regenerer_images=False : réutilise les images existantes dans images/home/ si présentes
                             (mode blog quotidien — évite 3 appels Replicate coûteux)
    """
    print("🏠 Génération page d'accueil...")
    articles = articles or []

    # ─── 3 images du slider ─────────────────────────────────────
    # get_image() gère automatiquement le cache via chemin_local :
    # - si le fichier existe déjà localement → réutilisé (0 appel Replicate)
    # - sinon → génération Replicate + téléchargement local
    # regenerer_images=True force une nouvelle génération en supprimant les fichiers
    if regenerer_images:
        for i in range(1, 4):
            f = Path(f"images/home/slider-{i}.webp")
            if f.exists():
                f.unlink()
        print("  🗑️ Anciennes images slider supprimées (regenerer_images=True)")

    img_slider_1 = get_image("modern bioclimatic pergola wooden deck mediterranean",
                             modele="dev", chemin_local="images/home/slider-1.webp")
    img_slider_2 = get_image("elegant aluminum pergola terrace garden evening lights",
                             modele="dev", chemin_local="images/home/slider-2.webp")
    img_slider_3 = get_image("wooden pergola with climbing plants provence french garden",
                             modele="dev", chemin_local="images/home/slider-3.webp")
    slider_urls = [img_slider_1["url"], img_slider_2["url"], img_slider_3["url"]]

    slides_html = ""
    for idx, url in enumerate(slider_urls, start=1):
        slides_html += f'''
      <div class="home-slide home-slide-{idx}" style="background-image: url('{url}');">
        <div class="home-slide-overlay"></div>
      </div>'''

    # ─── Cards piliers (9 guides) ───────────────────────────────
    cards = "".join(f"""
    <a href="/{p['slug']}.html" class="pilier-card">
      <div class="pilier-card-body">
        <h2>{p['titre']}</h2><p>{p['description']}</p>
        <span class="voir-plus">Voir le guide →</span>
      </div>
    </a>""" for p in archi["piliers"])

    # ─── Derniers articles en HTML statique (avec miniatures) ───
    derniers_cards = ""
    if articles:
        for art in articles[:6]:  # 6 derniers articles
            thumb = art.get("thumb", "")
            img_html = (
                f'<img src="{thumb}" alt="{art["titre"]}" class="card-image" loading="lazy">'
                if thumb else
                '<div class="card-image card-image-placeholder">📄</div>'
            )
            description = art.get('description', '')[:100]
            derniers_cards += f"""
    <a href="/blog/{art['slug']}.html" class="article-card">
      {img_html}
      <div class="card-body">
        <span class="categorie">{art.get('categorie','Blog')}</span>
        <h3>{art['titre']}</h3>
        <p>{description}...</p>
      </div>
    </a>"""
    else:
        derniers_cards = '<p class="no-articles">Les premiers articles arrivent bientôt !</p>'

    # ─── CSS dédié à la home (inline pour ne pas toucher style.css) ─
    css_home = """
  <style>
    /* ═══ SLIDER ACCUEIL ═══════════════════════════════════════ */
    .home-slider{position:relative;width:100%;height:520px;overflow:hidden;margin:0;}
    .home-slide{position:absolute;top:0;left:0;width:100%;height:100%;
      background-size:cover;background-position:center;
      opacity:0;animation:homeSlide 15s infinite;}
    .home-slide-1{animation-delay:0s;}
    .home-slide-2{animation-delay:5s;}
    .home-slide-3{animation-delay:10s;}
    .home-slide-overlay{position:absolute;inset:0;
      background:linear-gradient(to bottom,rgba(0,0,0,.15) 0%,rgba(0,0,0,.55) 100%);}
    @keyframes homeSlide{
      0%,26%{opacity:0;}
      4%,22%{opacity:1;}
      /* 5s visible, 0.6s fondu, 3 slides -> cycle de 15s */
    }
    .home-slider-content{position:absolute;inset:0;display:flex;flex-direction:column;
      align-items:center;justify-content:center;text-align:center;color:#fff;
      padding:20px;z-index:2;}
    .home-slider-content h1{font-family:Georgia,serif;font-size:clamp(1.8rem,4vw,3rem);
      margin:0 0 16px;text-shadow:0 2px 8px rgba(0,0,0,.6);max-width:900px;}
    .home-slider-content p{font-size:clamp(1rem,1.5vw,1.25rem);margin:0;
      text-shadow:0 1px 4px rgba(0,0,0,.6);max-width:700px;}
    @media (max-width:768px){
      .home-slider{height:380px;}
    }

    /* ═══ INTRO FIXE ═══════════════════════════════════════════ */
    .home-intro{background:#fafaf7;padding:50px 0;border-bottom:1px solid #e8e8e0;}
    .home-intro-inner{max-width:820px;margin:0 auto;padding:0 20px;text-align:center;}
    .home-intro h2{font-family:Georgia,serif;color:var(--vert,#2d5a3d);
      font-size:1.8rem;margin:0 0 20px;}
    .home-intro p{font-size:1.05rem;line-height:1.75;color:#444;margin:0 0 14px;}
    .home-intro p:last-child{margin-bottom:0;}

    /* ═══ SECTIONS ═════════════════════════════════════════════ */
    .home-section{padding:50px 0;}
    .home-section-alt{background:#fafaf7;}
    .home-section h2.section-titre{font-family:Georgia,serif;color:var(--vert,#2d5a3d);
      font-size:1.8rem;text-align:center;margin:0 0 34px;}

    /* ═══ CONFIANCE (3 avantages) ══════════════════════════════ */
    .confiance-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));
      gap:28px;max-width:1000px;margin:0 auto;}
    .confiance-item{text-align:center;padding:20px;}
    .confiance-item .icone{font-size:2.5rem;margin-bottom:12px;display:block;}
    .confiance-item h3{font-family:Georgia,serif;color:var(--vert,#2d5a3d);
      font-size:1.15rem;margin:0 0 8px;}
    .confiance-item p{color:#555;font-size:.95rem;line-height:1.5;margin:0;}

    /* ═══ PLACEHOLDER VIGNETTE ARTICLE SANS IMAGE ══════════════ */
    .card-image-placeholder{display:flex;align-items:center;justify-content:center;
      font-size:2.5rem;background:#f0ede5;color:#a8a397;height:180px;}
    .no-articles{text-align:center;color:#888;padding:40px 0;}
  </style>"""

    # ─── Assemblage final ──────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{SITE_NOM} — Guide complet pergolas France</title>
  <meta name="description" content="Le guide de référence sur les pergolas en France. Prix, matériaux, installation, réglementation : tout pour choisir la pergola idéale.">
  {meta_commune()}
  <link rel="canonical" href="{SITE_URL}/">
  {lien_css()}
{css_home}
</head>
<body>
  {construire_header(archi, "racine")}

  <!-- ═══ SLIDER HERO ═══ -->
  <section class="home-slider" aria-label="Galerie pergolas">
    {slides_html}
    <div class="home-slider-content">
      <h1>{SITE_NOM} — le guide de référence des pergolas en France</h1>
      <p>Prix, matériaux, installation, réglementation : tout pour choisir la pergola idéale.</p>
    </div>
  </section>

  <!-- ═══ INTRO FIXE ═══ -->
  <section class="home-intro">
    <div class="home-intro-inner">
      <h2>Votre projet pergola commence ici</h2>
      <p>Bienvenue sur <strong>{SITE_NOM}</strong>, le site français dédié à l'univers des pergolas. Que vous prépariez l'installation d'une <strong>pergola bioclimatique</strong>, d'une <strong>pergola en bois</strong> ou en <strong>aluminium</strong>, vous trouverez ici toutes les informations pour faire le bon choix.</p>
      <p>Nos guides couvrent <strong>les prix du marché français 2025-2026</strong>, les démarches administratives (permis de construire, déclaration préalable), les techniques d'installation et tous les critères qui comptent vraiment pour réussir votre projet.</p>
      <p>Avec plus de <strong>60 pages détaillées</strong> et des articles ajoutés chaque semaine, nous accompagnons chaque année des milliers de propriétaires français dans leur projet d'aménagement extérieur.</p>
    </div>
  </section>

  <!-- ═══ ADSENSE HAUT ═══ -->
  <div class="container">
    {bloc_adsense(ADSENSE_SLOT_HAUT, "horizontal")}
  </div>

  <!-- ═══ PILIERS ═══ -->
  <section class="home-section">
    <div class="container">
      <h2 class="section-titre">Nos guides thématiques</h2>
      <div class="piliers-grid">{cards}</div>
    </div>
  </section>

  <!-- ═══ ADSENSE MILIEU ═══ -->
  <div class="container">
    {bloc_adsense(ADSENSE_SLOT_MILIEU, "inArticle")}
  </div>

  <!-- ═══ DERNIERS ARTICLES ═══ -->
  <section class="home-section home-section-alt">
    <div class="container">
      <h2 class="section-titre">Nos derniers articles</h2>
      <div class="articles-grid">{derniers_cards}</div>
      <div style="text-align:center;margin-top:30px;">
        <a href="/blog.html" class="btn-hero">Voir tous nos articles →</a>
      </div>
    </div>
  </section>

  <!-- ═══ ADSENSE BAS ═══ -->
  <div class="container">
    {bloc_adsense(ADSENSE_SLOT_BAS, "horizontal")}
  </div>

  <!-- ═══ POURQUOI NOUS FAIRE CONFIANCE ═══ -->
  <section class="home-section">
    <div class="container">
      <h2 class="section-titre">Pourquoi nous faire confiance ?</h2>
      <div class="confiance-grid">
        <div class="confiance-item">
          <span class="icone">🎯</span>
          <h3>Infos à jour 2025-2026</h3>
          <p>Prix, normes et réglementation actualisés pour le marché français.</p>
        </div>
        <div class="confiance-item">
          <span class="icone">📚</span>
          <h3>60+ guides détaillés</h3>
          <p>Une couverture complète : matériaux, dimensions, installation, prix.</p>
        </div>
        <div class="confiance-item">
          <span class="icone">🇫🇷</span>
          <h3>100% français</h3>
          <p>Contenu adapté aux spécificités du marché et des démarches françaises.</p>
        </div>
      </div>
    </div>
  </section>

  {construire_footer("racine")}
  {lien_js()}
</body></html>"""
    Path("index.html").write_text(html, encoding="utf-8")
    print("✅ index.html")

# ─── PAGE PILIER ──────────────────────────────────────────
def generer_page_pilier(pilier, archi, keywords=None, articles=None):
    print(f"📌 Pilier : {pilier['titre']}...")
    articles = articles or []
    
    # 2 images FLUX.1-dev
    img1 = get_image(f"pergola {pilier['id']} terrace garden",
                     modele="dev",
                     chemin_local=f"images/piliers/{pilier['slug']}-1.webp")
    img2 = get_image(f"pergola {pilier['id']} installation detail",
                     modele="dev",
                     chemin_local=f"images/piliers/{pilier['slug']}-2.webp")

    kw_block = formater_keywords_prompt(pilier['id'], keywords or {})

    prompt = f"""Tu es expert SEO et rédacteur web pergolas France, avec 10 ans d'expérience dans la rédaction de pages piliers qui rankent top 3 sur Google.
Tu rédiges une page pilier PARFAITEMENT optimisée SEO : {pilier['titre']}
{kw_block}
OBJECTIF : cette page doit être LA référence française sur le sujet, battre la concurrence (Tryba, Leroy Merlin, Castorama) et ranker dans le top 3 Google.

CONSIGNES DE FOND :
1. Français naturel expert, public français acheteur, ton professionnel mais accessible
2. Couverture EXHAUSTIVE du sujet — le lecteur ne doit avoir aucune question sans réponse
3. Prix réalistes en euros (marché France 2025-2026), avec fourchettes précises (ex: "entre 3 500 € et 6 800 € pour du 3x4m posé")
4. **Longueur : 3000 à 4000 mots** dans la partie <CONTENU> — c'est NON NÉGOCIABLE, une page pilier trop courte ne rank pas
5. Exemples concrets, cas pratiques, chiffres précis
6. Mention de marques/fabricants français connus quand pertinent
7. Au moins 1 lien externe sortant vers une source officielle (service-public.fr, ADEME, RT 2020, normes AFNOR...)

STRUCTURE HN OBLIGATOIRE :
- 1 seul H1 (repris du format ci-dessous)
- **6 à 10 H2** couvrant : définition/principe, prix détaillé, matériaux, installation, réglementation, choix/critères, comparatif, cas d'usage, entretien
- **2 à 3 H3 sous chaque H2** pour approfondir
- **Au moins 3 listes <ul>** (critères, avantages, étapes...)
- **1 tableau comparatif HTML** (<table>) minimum avec <thead> et <tbody> — essentiel pour le SEO
- Chaque H2 intègre un mot-clé longue traîne naturellement

DENSITÉ MOT-CLÉ :
- Mot-clé principal : 1 à 1,5% du texte (naturellement, pas de bourrage)
- Variantes sémantiques (LSI) partout : synonymes, pluriels, termes connexes
- Mot-clé principal OBLIGATOIRE dans : H1, première phrase de l'intro, au moins 3 H2, et 5+ fois dans le corps

Format STRICT :
<META>description 150-155 car. avec mot-clé principal dans les 60 premiers caractères</META>
<H1>H1 optimisé avec mot-clé principal + année 2026 si pertinent</H1>
<INTRO>100-150 mots, mot-clé principal dans la 1ère phrase, promet ce que la page va apporter au lecteur</INTRO>
<CONTENU>[HTML complet : h2 h3 p ul table — 3000-4000 mots minimum]</CONTENU>
<FAQ1Q>question longue traîne complète (type "Combien coûte une...")</FAQ1Q><FAQ1R>réponse 3-4 phrases précises avec chiffres</FAQ1R>
<FAQ2Q>question</FAQ2Q><FAQ2R>réponse 3-4 phrases</FAQ2R>
<FAQ3Q>question</FAQ3Q><FAQ3R>réponse 3-4 phrases</FAQ3R>
<FAQ4Q>question</FAQ4Q><FAQ4R>réponse 3-4 phrases</FAQ4R>
<FAQ5Q>question</FAQ5Q><FAQ5R>réponse 3-4 phrases</FAQ5R>
<FAQ6Q>question</FAQ6Q><FAQ6R>réponse 3-4 phrases</FAQ6R>
<FAQ7Q>question</FAQ7Q><FAQ7R>réponse 3-4 phrases</FAQ7R>"""

    texte = appeler_claude(prompt, max_tokens=8000)

    h1      = extraire_balise(texte, "H1") or pilier["titre"]
    meta    = extraire_balise(texte, "META") or pilier["description"]
    intro   = extraire_balise(texte, "INTRO") or ""
    contenu = extraire_balise(texte, "CONTENU") or ""

    # FAQ
    qrs = []
    faq_html = ""
    for i in range(1, 8):  # 7 FAQ pour les piliers
        q = extraire_balise(texte, f"FAQ{i}Q")
        r = extraire_balise(texte, f"FAQ{i}R")
        if q:
            qrs.append({"q": q, "r": r})
            faq_html += f'<div class="faq-item"><button class="faq-question">{q}</button><div class="faq-reponse">{r}</div></div>\n'

    # Liens secondaires — URL : /{pilier_id}/{slug}.html
    liens_sec = "".join(
        f'<a href="/{pilier["id"]}/{s["slug"]}.html" class="lien-secondaire">→ {s["titre"]}</a>\n'
        for s in pilier["secondaires"]
    )

    # Articles récents du pilier (maillage statique) — liens absolus
    arts_pilier = [a for a in articles if a.get("pilier_id") == pilier["id"]][:4]
    arts_html = ""
    if arts_pilier:
        arts_html = '<div class="articles-pilier"><h2>Nos derniers articles</h2><div class="articles-grid">'
        for art in arts_pilier:
            arts_html += f"""
            <a href="/blog/{art['slug']}.html" class="article-card">
                <div class="card-body">
                    <h3>{art['titre']}</h3>
                    <p>{art.get('description','')[:80]}...</p>
                </div>
            </a>"""
        arts_html += '</div></div>'

    date_modified = datetime.now().strftime("%Y-%m-%d")

    # Schemas — URL pilier : {SITE_URL}/{slug}.html
    breadcrumb_schema = schema_breadcrumb([
        {"name": "Accueil", "url": f"{SITE_URL}/"},
        {"name": pilier["titre"], "url": f"{SITE_URL}/{pilier['slug']}.html"}
    ])
    faq_schema     = schema_faq(qrs)
    article_schema = schema_article(h1, meta, img1["url"], date_modified=date_modified)

    # HowTo pour installation
    howto_script = ""
    if pilier["id"] == "installation":
        etapes = [
            {"nom": "Préparer le terrain", "texte": "Délimitez la zone d'installation et vérifiez la planéité du sol."},
            {"nom": "Réaliser les fondations", "texte": "Coulez des semelles béton ou installez des platines selon le type de sol."},
            {"nom": "Monter la structure", "texte": "Assemblez les poteaux et la charpente selon les instructions du fabricant."},
            {"nom": "Poser la toiture", "texte": "Installez les lames, panneaux ou toiture selon le modèle choisi."},
            {"nom": "Finitions", "texte": "Vérifiez l'aplomb, serrez les fixations et effectuez les réglages finaux."},
        ]
        howto_script = f'<script type="application/ld+json">{schema_howto(h1, etapes)}</script>'

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{h1} | {SITE_NOM}</title>
  <meta name="description" content="{meta}">
  {meta_commune()}
  <link rel="canonical" href="{SITE_URL}/{pilier['slug']}.html">
  {lien_css()}
  <script type="application/ld+json">{article_schema}</script>
  <script type="application/ld+json">{breadcrumb_schema}</script>
  {f'<script type="application/ld+json">{faq_schema}</script>' if faq_schema else ''}
  {howto_script}
</head>
<body>
  {construire_header(archi, "pilier", pilier['id'])}
  <main class="container page-pilier">
    <nav class="fil-ariane">
      <a href="/">Accueil</a> › <span>{pilier['titre']}</span>
    </nav>
    <div class="pilier-hero">
      <img src="{img1['url']}" alt="{h1}" loading="lazy" width="1200">
      <div class="pilier-hero-content">
        <h1>{h1}</h1><p class="intro">{intro}</p>
      </div>
    </div>
    <div class="page-layout">
      <article class="contenu-principal">
        {bloc_adsense(ADSENSE_SLOT_HAUT, "horizontal")}
        <div class="article-body">{contenu}</div>
        <img src="{img2['url']}" alt="{h1} — détail installation" loading="lazy" width="1200" class="article-img-milieu">
        <p class="image-credit">Images générées par IA pour illustration</p>
        <div class="faq-section">
          <h2>Questions fréquentes sur {pilier['titre'].lower()}</h2>
          {faq_html}
        </div>
        {arts_html}
      </article>
      <aside class="sidebar">
        <div class="widget">
          <h3>Dans ce guide</h3>{liens_sec}
        </div>
        {bloc_adsense(ADSENSE_SLOT_SIDEBAR, "sidebar")}
      </aside>
    </div>
  </main>
  {construire_footer("pilier")}
  <script>const PILIER_ID = "{pilier['id']}";</script>
  {lien_js()}
</body></html>"""

    # Écriture à la racine : /{slug}.html
    Path(f"{pilier['slug']}.html").write_text(html, encoding="utf-8")
    print(f"  ✅ {pilier['slug']}.html")

# ─── PAGE SECONDAIRE ──────────────────────────────────────
def generer_page_secondaire(secondaire, pilier, archi, keywords=None, articles=None):
    print(f"  📄 Secondaire : {secondaire['titre']}...")
    articles = articles or []

    img = get_image(f"pergola {secondaire['mot_cle']}",
                    modele="schnell",
                    chemin_local=f"images/secondaires/{pilier['id']}-{secondaire['slug']}.webp")

    # KW liés
    kw_block = ""
    if keywords and pilier['id'] in keywords:
        data    = keywords[pilier['id']]
        termes  = secondaire.get('mot_cle', '').lower().split()
        kw_lies = [
            kw for kw in data.get('secondaires', []) + data.get('longue_traine', [])
            if any(t in kw['kw'].lower() for t in termes if len(t) > 3)
        ][:12]
        if kw_lies:
            kw_block = f"\n=== MOTS-CLÉS SEO (Ahrefs France) ===\nMot-clé cible : {secondaire['mot_cle']}\n"
            for kw in kw_lies:
                kw_block += f"  - {kw['kw']} ({kw['vol']:,}/mois)\n"
            kw_block += "======================================\n"

    prompt = f"""Tu es expert SEO et rédacteur web pergolas France, spécialisé dans les pages de conversion (intention d'achat).
Tu rédiges une page secondaire optimisée SEO : {secondaire['titre']}
Guide parent : {pilier['titre']}
{kw_block}
OBJECTIF : cette page doit ranker sur une requête ciblée à forte intention d'achat, et convaincre le lecteur d'aller plus loin (devis, comparaison, achat).

CONSIGNES DE FOND :
1. Français naturel expert, orienté aide à la décision achat
2. Prix réalistes en euros (marché France 2025-2026), fourchettes précises
3. **Longueur : 1400 à 1800 mots** dans la partie <CONTENU> — ne pas descendre sous 1400
4. Ton expert rassurant, lève les objections du lecteur
5. Exemples concrets, cas d'usage typiques, mini-comparatifs
6. Inclure au moins 1 liste à puces <ul> pour les critères/avantages

STRUCTURE HN OBLIGATOIRE :
- 1 seul H1 avec le mot-clé exact
- **5 à 7 H2** couvrant : prix, pour qui/quelle surface, modèles/options, installation, réglementation si pertinent, critères de choix, erreurs à éviter
- **H3 sous les H2 qui s'y prêtent** (surtout "prix" et "modèles")
- **Minimum 2 listes <ul>**
- Idéalement 1 mini-tableau comparatif HTML si le sujet s'y prête

DENSITÉ MOT-CLÉ :
- Mot-clé principal dans H1, première phrase intro, au moins 2 H2, 4+ fois dans le corps
- Variantes longue traîne naturellement réparties

Format STRICT :
<META>description 150-155 car. avec mot-clé principal</META>
<H1>H1 optimisé avec mot-clé exact</H1>
<INTRO>80-120 mots, mot-clé dans la 1ère phrase, promet la valeur de la page</INTRO>
<CONTENU>[HTML h2 h3 p ul — 1400-1800 mots minimum]</CONTENU>
<FAQ1Q>question longue traîne</FAQ1Q><FAQ1R>réponse 2-3 phrases précises</FAQ1R>
<FAQ2Q>question</FAQ2Q><FAQ2R>réponse 2-3 phrases</FAQ2R>
<FAQ3Q>question</FAQ3Q><FAQ3R>réponse 2-3 phrases</FAQ3R>
<FAQ4Q>question</FAQ4Q><FAQ4R>réponse 2-3 phrases</FAQ4R>"""

    texte   = appeler_claude(prompt, max_tokens=5000)
    h1      = extraire_balise(texte, "H1") or secondaire["titre"]
    meta    = extraire_balise(texte, "META") or secondaire["titre"]
    intro   = extraire_balise(texte, "INTRO") or ""
    contenu = extraire_balise(texte, "CONTENU") or ""

    qrs      = []
    faq_html = ""
    for i in range(1, 5):  # 4 FAQ pour les secondaires
        q = extraire_balise(texte, f"FAQ{i}Q")
        r = extraire_balise(texte, f"FAQ{i}R")
        if q:
            qrs.append({"q": q, "r": r})
            faq_html += f'<div class="faq-item"><button class="faq-question">{q}</button><div class="faq-reponse">{r}</div></div>\n'

    # Liens sœurs — URL : /{pilier_id}/{slug}.html
    liens_soeurs = "".join(
        f'<a href="/{pilier["id"]}/{s["slug"]}.html">→ {s["titre"]}</a>\n'
        for s in pilier["secondaires"] if s["slug"] != secondaire["slug"]
    )

    # Articles liés en HTML statique
    arts_connexes = generer_liens_blog_sur_secondaire(
        pilier['id'], secondaire['slug'], articles
    )

    date_modified = datetime.now().strftime("%Y-%m-%d")

    # Schemas — URLs mises à jour
    breadcrumb_schema = schema_breadcrumb([
        {"name": "Accueil", "url": f"{SITE_URL}/"},
        {"name": pilier["titre"], "url": f"{SITE_URL}/{pilier['slug']}.html"},
        {"name": secondaire["titre"], "url": f"{SITE_URL}/{pilier['id']}/{secondaire['slug']}.html"}
    ])
    faq_schema     = schema_faq(qrs)
    article_schema = schema_article(h1, meta, img["url"], date_modified=date_modified)

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{h1} | {SITE_NOM}</title>
  <meta name="description" content="{meta}">
  {meta_commune()}
  <link rel="canonical" href="{SITE_URL}/{pilier['id']}/{secondaire['slug']}.html">
  {lien_css()}
  <script type="application/ld+json">{article_schema}</script>
  <script type="application/ld+json">{breadcrumb_schema}</script>
  {f'<script type="application/ld+json">{faq_schema}</script>' if faq_schema else ''}
</head>
<body>
  {construire_header(archi, "secondaire", pilier['id'])}
  <main class="container">
    <nav class="fil-ariane">
      <a href="/">Accueil</a> ›
      <a href="/{pilier['slug']}.html">{pilier['titre']}</a> ›
      <span>{secondaire['titre']}</span>
    </nav>
    <div class="page-layout">
      <article class="contenu-principal">
        <img src="{img['url']}" alt="{h1}" class="article-img" loading="lazy" width="1200">
        <p class="image-credit">Image générée par IA pour illustration</p>
        <h1>{h1}</h1>
        <p class="intro">{intro}</p>
        <div class="article-body">{contenu}</div>
        {bloc_adsense(ADSENSE_SLOT_MILIEU, "inArticle")}
        <div class="faq-section">
          <h2>Questions fréquentes</h2>{faq_html}
        </div>
        <div class="articles-connexes">
          <h2>Articles de blog sur ce sujet</h2>
          {arts_connexes}
        </div>
      </article>
      <aside class="sidebar">
        <div class="widget">
          <h3>Guide {pilier['titre']}</h3>
          <a href="/{pilier['slug']}.html">← Retour au guide complet</a>
          <h4 style="margin:12px 0 8px;font-size:.9rem;color:var(--vert)">Pages du guide</h4>
          {liens_soeurs}
        </div>
        {bloc_adsense(ADSENSE_SLOT_SIDEBAR, "sidebar")}
      </aside>
    </div>
  </main>
  {construire_footer("secondaire")}
  <script>const PILIER_ID="{pilier['id']}"; const PAGE_SLUG="{secondaire['slug']}";</script>
  {lien_js()}
</body></html>"""

    # Écriture : /{pilier_id}/{slug}.html (plus de /secondaires/)
    Path(f"{pilier['id']}/{secondaire['slug']}.html").write_text(html, encoding="utf-8")

# ─── ARTICLE DE BLOG ──────────────────────────────────────
def generer_article_blog(archi, keywords=None, comments_config=None):
    sujets_file = Path("sujets.json")
    if not sujets_file.exists():
        print("❌ sujets.json introuvable"); return

    sujets   = json.loads(sujets_file.read_text(encoding="utf-8"))
    traites_file = Path("sujets_traites.json")
    traites  = json.loads(traites_file.read_text()) if traites_file.exists() else []
    restants = [s for s in sujets if s["slug"] not in traites] or sujets

    sujet = random.choice(restants)
    traites.append(sujet["slug"])
    traites_file.write_text(json.dumps(traites, ensure_ascii=False))

    # Pilier parent
    pilier_parent     = None
    secondaire_parent = None
    for p in archi["piliers"]:
        if p["id"] == sujet.get("pilier_id"):
            pilier_parent = p
            for s in p["secondaires"]:
                if s["slug"] == sujet.get("secondaire_slug"):
                    secondaire_parent = s
            break

    img = get_image(f"pergola {sujet.get('mot_cle','jardin')}",
                    modele="schnell",
                    chemin_local=f"images/blog/{sujet['slug']}.webp")

    # Ancres diversifiées — URLs absolues
    ancre_pilier = ""
    ancre_sec    = ""
    url_pilier   = ""
    url_sec      = ""
    if pilier_parent and comments_config:
        ancre_pilier = ancre_aleatoire(pilier_parent['id'], comments_config)
        url_pilier   = f"/{pilier_parent['slug']}.html"
    if secondaire_parent and pilier_parent:
        ancre_sec = secondaire_parent.get('mot_cle', secondaire_parent['titre'])
        url_sec   = f"/{pilier_parent['id']}/{secondaire_parent['slug']}.html"

    # KW liés
    kw_block = ""
    if keywords and sujet.get('pilier_id') in keywords:
        data   = keywords[sujet['pilier_id']]
        termes = sujet.get('mot_cle', '').lower().split()
        kw_lies = [
            kw for kw in data.get('secondaires', []) + data.get('longue_traine', [])
            if any(t in kw['kw'].lower() for t in termes if len(t) > 3)
        ][:8]
        if kw_lies:
            kw_block = "\nMots-clés SEO à intégrer :\n" + "\n".join(
                f"  - {kw['kw']} ({kw['vol']:,}/mois)" for kw in kw_lies
            ) + "\n"

    # Instructions maillage contextuel
    maillage_instructions = ""
    if url_pilier and ancre_pilier:
        maillage_instructions += f"""
MAILLAGE INTERNE OBLIGATOIRE dans le corps de l'article (pas à la fin) :
1. Intègre naturellement dans un paragraphe <p> un lien HTML vers le guide pilier :
   <a href="{url_pilier}">{ancre_pilier}</a>
   L'ancre DOIT être exactement : "{ancre_pilier}"
   Le lien doit être dans une phrase qui parle de ce sujet, pas isolé."""
    if url_sec and ancre_sec:
        maillage_instructions += f"""
2. Intègre naturellement dans un autre paragraphe <p> un lien vers la page secondaire :
   <a href="{url_sec}">{ancre_sec}</a>
   L'ancre DOIT être exactement : "{ancre_sec}"
   Le lien doit être dans une phrase contextuelle pertinente."""

    prompt = f"""Tu es expert SEO et rédacteur web pergolas France, spécialisé dans les articles qui rankent ET qui apparaissent dans Google Discover.
Tu rédiges un article de blog optimisé SEO ET Google Discover sur : {sujet['titre']}
Mot-clé cible : {sujet['mot_cle']}
{kw_block}
{maillage_instructions}

OBJECTIF : article utile, concret, qui se lit facilement sur mobile et donne envie de cliquer depuis Discover.

CONSIGNES DE FOND :
- Titre accrocheur façon Discover (curiosité, chiffre, utilité, émotion) — PAS de clickbait vulgaire
- Français naturel, pratique, ton journalistique mais expert
- **Longueur : 1200 à 1600 mots** dans la partie <CONTENU> — ne pas descendre sous 1200
- Prix en euros (marché France 2025-2026), conseils actionnables
- Au moins 1 exemple concret ou cas pratique avec chiffres
- Les liens de maillage doivent être dans le corps du texte (dans des paragraphes <p>), pas dans une section séparée

STRUCTURE HN OBLIGATOIRE :
- 1 seul H1 avec mot-clé + accroche Discover (le H1 est fourni ci-dessous, pas besoin de le régénérer)
- **4 à 6 H2** : problème/contexte, solutions/points clés, cas pratique, erreurs à éviter, conseil final
- **H3 là où ça approfondit** (pas systématique, plus narratif qu'un pilier)
- **Au moins 2 listes <ul>** (critères, étapes, conseils)

DENSITÉ MOT-CLÉ :
- Mot-clé cible dans 1ère phrase intro, au moins 1 H2, 3+ fois dans le corps
- Variantes sémantiques naturellement

Format STRICT :
<META>description 150-155 car. accrocheuse avec mot-clé</META>
<INTRO>80-120 mots : crochet émotionnel/curiosité + promesse de ce que l'article apporte + mot-clé dans la 1ère phrase</INTRO>
<CONTENU>[HTML complet avec H2, H3, p, ul — liens de maillage intégrés dans les paragraphes — 1200-1600 mots minimum]</CONTENU>
<FAQ1Q>question longue traîne</FAQ1Q><FAQ1R>réponse 2-3 phrases</FAQ1R>
<FAQ2Q>question</FAQ2Q><FAQ2R>réponse 2-3 phrases</FAQ2R>
<FAQ3Q>question</FAQ3Q><FAQ3R>réponse 2-3 phrases</FAQ3R>
<FAQ4Q>question</FAQ4Q><FAQ4R>réponse 2-3 phrases</FAQ4R>"""

    texte   = appeler_claude(prompt, max_tokens=4000)
    meta    = extraire_balise(texte, "META") or sujet["titre"]
    intro   = extraire_balise(texte, "INTRO") or ""
    contenu = extraire_balise(texte, "CONTENU") or ""

    qrs      = []
    faq_html = ""
    for i in range(1, 5):  # 4 FAQ pour les articles blog
        q = extraire_balise(texte, f"FAQ{i}Q")
        r = extraire_balise(texte, f"FAQ{i}R")
        if q:
            qrs.append({"q": q, "r": r})
            faq_html += f'<div class="faq-item"><button class="faq-question">{q}</button><div class="faq-reponse">{r}</div></div>\n'

    date_iso = datetime.now().strftime("%Y-%m-%d")

    # Articles similaires (chargés depuis articles.json existant)
    articles_existants = charger_articles()
    similaires_html    = generer_articles_similaires(
        sujet["slug"], sujet.get("pilier_id", ""), articles_existants
    )

    # Schemas — URLs absolues mises à jour
    breadcrumb_items = [{"name": "Accueil", "url": f"{SITE_URL}/"}]
    if pilier_parent:
        breadcrumb_items.append({
            "name": pilier_parent["titre"],
            "url": f"{SITE_URL}/{pilier_parent['slug']}.html"
        })
    breadcrumb_items.append({
        "name": sujet["titre"],
        "url": f"{SITE_URL}/blog/{sujet['slug']}.html"
    })

    breadcrumb_schema = schema_breadcrumb(breadcrumb_items)
    faq_schema        = schema_faq(qrs)
    article_schema    = schema_article(
        sujet["titre"], meta, img["url"],
        date_published=date_iso, date_modified=date_iso
    )

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{sujet['titre']} | {SITE_NOM}</title>
  <meta name="description" content="{meta}">
  {meta_commune()}
  <link rel="canonical" href="{SITE_URL}/blog/{sujet['slug']}.html">
  {lien_css()}
  <script type="application/ld+json">{article_schema}</script>
  <script type="application/ld+json">{breadcrumb_schema}</script>
  {f'<script type="application/ld+json">{faq_schema}</script>' if faq_schema else ''}
</head>
<body>
  {construire_header(archi, "blog", sujet.get('pilier_id'))}
  <main class="container">
    <nav class="fil-ariane">
      <a href="/">Accueil</a> ›
      {f"<a href='/{pilier_parent['slug']}.html'>{pilier_parent['titre']}</a> ›" if pilier_parent else ""}
      <span>{sujet['titre']}</span>
    </nav>
    <div class="page-layout">
      <article class="contenu-principal">
        <span class="categorie">{sujet.get('categorie','Blog')}</span>
        <h1>{sujet['titre']}</h1>
        <p class="intro">{intro}</p>
        <img src="{img['url']}" alt="{sujet['titre']}" class="article-img" loading="lazy" width="1200">
        <p class="image-credit">Image générée par IA pour illustration</p>
        {bloc_adsense(ADSENSE_SLOT_MILIEU, "inArticle")}
        <div class="article-body">{contenu}</div>
        <div class="faq-section">
          <h2>Questions fréquentes</h2>{faq_html}
        </div>
        {similaires_html}
        {bloc_adsense(ADSENSE_SLOT_BAS, "horizontal")}
        <div class="commentaires-section" id="commentaires">
          <h2>Commentaires</h2>
          <div id="liste-commentaires"><!-- Commentaires chargés dynamiquement --></div>
        </div>
      </article>
      <aside class="sidebar">
        <div class="widget" id="widget-recents"></div>
        {bloc_adsense(ADSENSE_SLOT_SIDEBAR, "sidebar")}
      </aside>
    </div>
  </main>
  {construire_footer("blog")}
  <script>
    const PILIER_ID  = "{sujet.get('pilier_id','')}";
    const ARTICLE_SLUG = "{sujet['slug']}";
  </script>
  {lien_js()}
</body></html>"""

    Path(f"blog/{sujet['slug']}.html").write_text(html, encoding="utf-8")

    # Mise à jour articles.json
    index_file = Path("articles.json")
    articles   = json.loads(index_file.read_text(encoding="utf-8")) if index_file.exists() else []

    # Thumb = la même image que celle de l'article (stockée en local, donc permanente)
    # Le navigateur redimensionnera naturellement via l'attribut CSS .card-image
    articles.insert(0, {
        "slug": sujet["slug"],
        "titre": sujet["titre"],
        "categorie": sujet.get("categorie","Blog"),
        "description": meta,
        "date": date_iso,
        "thumb": img.get("url",""),
        "pilier_id": sujet.get("pilier_id",""),
        "secondaire_slug": sujet.get("secondaire_slug","")
    })
    articles = articles[:500]
    index_file.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")

    # Régénérer page secondaire parente (maillage statique)
    if secondaire_parent and pilier_parent:
        print(f"  🔄 Mise à jour maillage page secondaire...")
        generer_page_secondaire(secondaire_parent, pilier_parent, archi, keywords, articles)

    # Initialiser le planning de commentaires
    initialiser_planning_commentaires(sujet, articles)

    generer_page_blog(archi, articles)
    generer_accueil(archi, articles, regenerer_images=False)  # miniatures home à jour, slider cached
    generer_sitemap(archi, articles)
    ping_google_sitemap()
    print(f"✅ blog/{sujet['slug']}.html")

# ─── PLANNING COMMENTAIRES ────────────────────────────────
def initialiser_planning_commentaires(sujet, articles):
    """Crée le planning de commentaires pour un nouvel article."""
    from datetime import timedelta

    planning_file = Path("comments_planning.json")
    planning      = json.loads(planning_file.read_text(encoding="utf-8")) if planning_file.exists() else {}

    if sujet["slug"] in planning:
        return  # Déjà planifié

    # Déterminer la popularité selon le volume du mot-clé
    vol = sujet.get("volume", 0)
    if vol > 5000:
        popularite = "tres_haute"; min_c, max_c = 5, 8; prob_zero = 0.03
    elif vol > 1000:
        popularite = "haute";      min_c, max_c = 3, 5; prob_zero = 0.10
    elif vol > 500:
        popularite = "moyenne";    min_c, max_c = 1, 3; prob_zero = 0.30
    elif vol > 100:
        popularite = "faible";     min_c, max_c = 0, 2; prob_zero = 0.50
    else:
        popularite = "tres_faible";min_c, max_c = 0, 1; prob_zero = 0.70

    # Tirage aléatoire : cet article aura-t-il des commentaires ?
    if random.random() < prob_zero:
        planning[sujet["slug"]] = {"popularite": popularite, "nb_commentaires": 0, "planning": []}
        planning_file.write_text(json.dumps(planning, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    nb_total    = random.randint(min_c, max_c)
    date_pub    = datetime.strptime(sujet.get("date", datetime.now().strftime("%Y-%m-%d")), "%Y-%m-%d")
    commentaires = []

    # Charger les profils
    config   = charger_comments_config()
    profils  = config.get("profils", [])
    types_c  = config.get("types_commentaires", ["question_pratique"])
    
    # Sélectionner des profils uniques pour cet article
    profils_article = random.sample(profils, min(nb_total * 2, len(profils)))
    
    date_courante = date_pub
    idx_profil    = 0

    for i in range(nb_total):
        # Délai avant ce commentaire
        if i == 0:
            delai = random.randint(5, 14)
        else:
            delai = random.randint(2, 7)
        
        date_courante += timedelta(days=delai + random.randint(0, 2))
        profil = profils_article[idx_profil % len(profils_article)]
        idx_profil += 1

        commentaire = {
            "id": f"c{i}",
            "type": "commentaire",
            "profil": profil["nom"],
            "region": profil["region"],
            "style": profil["style"],
            "type_message": random.choice(types_c),
            "date_prevue": date_courante.strftime("%Y-%m-%d"),
            "statut": "pending",
            "reponses": []
        }

        # Ce commentaire aura-t-il une réponse ?
        if random.random() > 0.40:
            delai_rep = random.randint(1, 4)
            date_rep  = date_courante + timedelta(days=delai_rep)
            profil_rep = profils_article[idx_profil % len(profils_article)]
            idx_profil += 1

            reponse = {
                "id": f"r{i}_0",
                "type": "reponse",
                "profil": profil_rep["nom"],
                "region": profil_rep["region"],
                "style": profil_rep["style"],
                "type_message": random.choice(["complement_information", "retour_experience_positif", "conseil_materiau"]),
                "date_prevue": date_rep.strftime("%Y-%m-%d"),
                "statut": "pending"
            }

            # Contre-réponse ?
            if random.random() > 0.65:
                delai_cr  = random.randint(1, 3)
                date_cr   = date_rep + timedelta(days=delai_cr)
                profil_cr = profils_article[idx_profil % len(profils_article)]
                idx_profil += 1

                reponse["contre_reponse"] = {
                    "id": f"cr{i}_0",
                    "type": "contre_reponse",
                    "profil": profil_cr["nom"],
                    "region": profil_cr["region"],
                    "style": profil_cr["style"],
                    "type_message": "remerciement_avec_question",
                    "date_prevue": date_cr.strftime("%Y-%m-%d"),
                    "statut": "pending"
                }

            commentaire["reponses"].append(reponse)
        
        commentaires.append(commentaire)

    planning[sujet["slug"]] = {
        "popularite": popularite,
        "titre": sujet["titre"],
        "pilier_id": sujet.get("pilier_id",""),
        "nb_commentaires": nb_total,
        "planning": commentaires
    }

    planning_file.write_text(json.dumps(planning, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  📅 Planning: {nb_total} commentaires prévus ({popularite})")

# ─── GÉNÉRATION COMMENTAIRES (workflow quotidien) ──────────
def generer_commentaires_du_jour(archi):
    """Appelé quotidiennement par comments.yml"""
    planning_file = Path("comments_planning.json")
    if not planning_file.exists():
        print("Aucun planning trouvé"); return

    planning = json.loads(planning_file.read_text(encoding="utf-8"))
    comments_file = Path("comments.json")
    comments_data = json.loads(comments_file.read_text(encoding="utf-8")) if comments_file.exists() else {}
    
    aujourd_hui = datetime.now().strftime("%Y-%m-%d")
    articles    = charger_articles()
    modifie     = False

    for slug, data in planning.items():
        for item in data.get("planning", []):
            if item["statut"] != "pending":
                continue
            if item["date_prevue"] > aujourd_hui:
                continue

            # Générer ce commentaire
            art_info = next((a for a in articles if a["slug"] == slug), {})
            texte_c  = generer_texte_commentaire(item, data["titre"], art_info)
            
            if slug not in comments_data:
                comments_data[slug] = []

            comment_obj = {
                "id": item["id"],
                "auteur": item["profil"],
                "region": item["region"],
                "date": item["date_prevue"],
                "texte": texte_c,
                "reponses": []
            }

            # Traiter les réponses
            for rep in item.get("reponses", []):
                if rep["statut"] == "pending" and rep["date_prevue"] <= aujourd_hui:
                    texte_r = generer_texte_commentaire(rep, data["titre"], art_info, parent_texte=texte_c)
                    rep_obj = {
                        "id": rep["id"],
                        "auteur": rep["profil"],
                        "region": rep["region"],
                        "date": rep["date_prevue"],
                        "texte": texte_r,
                        "reponses": []
                    }
                    # Contre-réponse
                    cr = rep.get("contre_reponse", {})
                    if cr and cr.get("statut") == "pending" and cr.get("date_prevue", "9999") <= aujourd_hui:
                        texte_cr = generer_texte_commentaire(cr, data["titre"], art_info, parent_texte=texte_r)
                        rep_obj["reponses"].append({
                            "id": cr["id"],
                            "auteur": cr["profil"],
                            "region": cr["region"],
                            "date": cr["date_prevue"],
                            "texte": texte_cr
                        })
                        cr["statut"] = "done"

                    comment_obj["reponses"].append(rep_obj)
                    rep["statut"] = "done"

            comments_data[slug].append(comment_obj)
            item["statut"] = "done"
            modifie = True
            print(f"  💬 Commentaire généré pour {slug} par {item['profil']}")

            # Régénérer la page blog avec les commentaires
            regenerer_blog_avec_commentaires(slug, comments_data, archi, articles)

    if modifie:
        planning_file.write_text(json.dumps(planning, ensure_ascii=False, indent=2), encoding="utf-8")
        comments_file.write_text(json.dumps(comments_data, ensure_ascii=False, indent=2), encoding="utf-8")

def generer_texte_commentaire(item, titre_article, art_info, parent_texte=None):
    """Génère le texte d'un commentaire via Claude."""
    type_msg = item["type_message"]
    profil   = item["profil"]
    style    = item["style"]
    region   = item["region"]

    contexte_parent = f"\nIl répond à ce commentaire précédent : '{parent_texte[:150]}...'" if parent_texte else ""

    prompt = f"""Tu es {profil}, habitant(e) en {region}. 
Ton style : {style}
Tu laisses un commentaire de type "{type_msg}" sur cet article : "{titre_article}"
{contexte_parent}

CONSIGNES ABSOLUES :
- Écris UNIQUEMENT le texte du commentaire, rien d'autre
- 2-4 phrases maximum, ton naturel et humain
- Parle en français naturel, pas d'anglicismes
- Mentionne ta région si c'est naturel dans le contexte
- Sois spécifique à l'article, pas générique
- Pour "question_pratique" : pose une vraie question pratique
- Pour "retour_experience" : partage une vraie expérience personnelle avec détails
- Pour "demande_prix_devis" : demande des prix pour une situation précise
- Pour "complement_information" : ajoute une info utile et spécifique
- Pour "remerciement_avec_question" : remercie puis pose une question
- Varie le niveau de langue selon le profil (ouvrier vs médecin vs retraité)
- NE PAS commencer par "Bonjour" ou "Merci pour cet article"

Écris uniquement le texte du commentaire :"""

    return appeler_claude(prompt, max_tokens=200)

def regenerer_blog_avec_commentaires(slug, comments_data, archi, articles):
    """Ajoute les commentaires en HTML statique dans la page blog."""
    blog_file = Path(f"blog/{slug}.html")
    if not blog_file.exists():
        return

    html = blog_file.read_text(encoding="utf-8")
    commentaires = comments_data.get(slug, [])

    if not commentaires:
        return

    # Générer HTML commentaires
    html_comments = '<div class="commentaires-section" id="commentaires"><h2>Commentaires</h2><div id="liste-commentaires">'
    
    for c in commentaires:
        initiale = c["auteur"][0].upper()
        html_comments += f"""
        <div class="commentaire" id="{c['id']}">
            <div class="comment-header">
                <span class="comment-avatar">{initiale}</span>
                <strong class="comment-auteur">{c['auteur']}</strong>
                <span class="comment-region">{c.get('region','')}</span>
                <span class="comment-date">{c['date']}</span>
            </div>
            <p class="comment-texte">{c['texte']}</p>"""
        
        for r in c.get("reponses", []):
            initiale_r = r["auteur"][0].upper()
            html_comments += f"""
            <div class="commentaire reponse" id="{r['id']}">
                <div class="comment-header">
                    <span class="comment-avatar">{initiale_r}</span>
                    <strong class="comment-auteur">{r['auteur']}</strong>
                    <span class="comment-region">{r.get('region','')}</span>
                    <span class="comment-date">{r['date']}</span>
                </div>
                <p class="comment-texte">{r['texte']}</p>"""
            
            for cr in r.get("reponses", []):
                initiale_cr = cr["auteur"][0].upper()
                html_comments += f"""
                <div class="commentaire contre-reponse" id="{cr['id']}">
                    <div class="comment-header">
                        <span class="comment-avatar">{initiale_cr}</span>
                        <strong class="comment-auteur">{cr['auteur']}</strong>
                        <span class="comment-region">{cr.get('region','')}</span>
                        <span class="comment-date">{cr['date']}</span>
                    </div>
                    <p class="comment-texte">{cr['texte']}</p>
                </div>"""
            
            html_comments += '</div>'
        
        html_comments += '</div>'
    
    html_comments += '</div></div>'

    # Remplacer la section commentaires
    html = re.sub(
        r'<div class="commentaires-section".*?</div>\s*</div>',
        html_comments,
        html,
        flags=re.DOTALL
    )
    blog_file.write_text(html, encoding="utf-8")
    print(f"  ✅ Commentaires mis à jour : {slug}")

# ─── PAGE BLOG ────────────────────────────────────────────
def generer_page_blog(archi, articles):
    cards = ""
    for art in articles[:50]:
        thumb = art.get("thumb","")
        img   = f'<img src="{thumb}" alt="{art["titre"]}" class="card-image" loading="lazy">' if thumb else ""
        cards += f"""
    <a href="/blog/{art['slug']}.html" class="article-card">
      {img}
      <div class="card-body">
        <span class="categorie">{art['categorie']}</span>
        <h2>{art['titre']}</h2>
        <p>{art.get('description','')[:100]}...</p>
      </div>
    </a>"""

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Blog Pergola | {SITE_NOM}</title>
  <meta name="description" content="Tous nos articles et conseils sur les pergolas en France.">
  {meta_commune()}
  <link rel="canonical" href="{SITE_URL}/blog.html">
  {lien_css()}
</head>
<body>
  {construire_header(archi, "racine")}
  <main class="container">
    <h1 style="font-family:Georgia,serif;color:var(--vert);padding:40px 0 24px;">Blog & Conseils Pergola</h1>
    <div class="articles-grid">{cards}</div>
  </main>
  {construire_footer("racine")}
  {lien_js()}
</body></html>"""
    Path("blog.html").write_text(html, encoding="utf-8")

# ─── SITEMAP ──────────────────────────────────────────────
def generer_sitemap(archi, articles):
    urls = [f'<url><loc>{SITE_URL}/</loc><priority>1.0</priority><changefreq>daily</changefreq></url>']
    urls.append(f'<url><loc>{SITE_URL}/blog.html</loc><priority>0.9</priority><changefreq>daily</changefreq></url>')
    for p in archi["piliers"]:
        # URL pilier : /{slug}.html
        urls.append(f'<url><loc>{SITE_URL}/{p["slug"]}.html</loc><priority>0.9</priority><changefreq>monthly</changefreq></url>')
        for s in p["secondaires"]:
            # URL secondaire : /{pilier_id}/{slug}.html
            urls.append(f'<url><loc>{SITE_URL}/{p["id"]}/{s["slug"]}.html</loc><priority>0.8</priority><changefreq>monthly</changefreq></url>')
    for art in articles:
        urls.append(f'<url><loc>{SITE_URL}/blog/{art["slug"]}.html</loc><lastmod>{art["date"]}</lastmod><priority>0.6</priority><changefreq>yearly</changefreq></url>')

    Path("sitemap.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{''.join(urls)}
</urlset>""", encoding="utf-8")
    print("✅ sitemap.xml")

def ping_google_sitemap():
    """Notifie Google du nouveau sitemap."""
    try:
        url = f"https://www.google.com/ping?sitemap={urllib.parse.quote(f'{SITE_URL}/sitemap.xml')}"
        urllib.request.urlopen(url, timeout=5)
        print("✅ Google pingué")
    except Exception as e:
        print(f"  ⚠️ Ping Google: {e}")

# ─── MAIN ─────────────────────────────────────────────────
def main():
    import sys
    archi           = charger_architecture()
    keywords        = charger_keywords()
    comments_config = charger_comments_config()
    mode = sys.argv[1] if len(sys.argv) > 1 else "blog"

    if mode == "full":
        print("🚀 Construction complète du site...")
        # Créer dossiers : un par pilier (pour les secondaires) + blog
        Path("blog").mkdir(exist_ok=True)
        for pilier in archi["piliers"]:
            Path(pilier["id"]).mkdir(exist_ok=True)

        articles = charger_articles()
        generer_accueil(archi, articles, regenerer_images=True)

        for pilier in archi["piliers"]:
            generer_page_pilier(pilier, archi, keywords, articles)
            for secondaire in pilier["secondaires"]:
                generer_page_secondaire(secondaire, pilier, archi, keywords, articles)

        generer_page_blog(archi, articles)
        generer_sitemap(archi, articles)
        print("🎉 Site complet généré !")

    elif mode == "blog":
        print("📝 Génération article quotidien...")
        Path("blog").mkdir(exist_ok=True)
        generer_article_blog(archi, keywords, comments_config)
        print("🎉 Article publié !")

    elif mode == "comments":
        print("💬 Génération commentaires du jour...")
        generer_commentaires_du_jour(archi)
        print("🎉 Commentaires mis à jour !")

if __name__ == "__main__":
    main()
