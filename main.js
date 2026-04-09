// main.js — Pergola Guide France

// ─── FAQ accordéon ───────────────────────────────────────
document.querySelectorAll('.faq-question').forEach(btn => {
  btn.addEventListener('click', () => {
    const reponse = btn.nextElementSibling;
    const isOpen = btn.classList.contains('open');
    document.querySelectorAll('.faq-question.open').forEach(b => {
      b.classList.remove('open');
      b.nextElementSibling.classList.remove('open');
    });
    if (!isOpen) {
      btn.classList.add('open');
      reponse.classList.add('open');
    }
  });
});

// ─── Menu mobile ─────────────────────────────────────────
function toggleMenu() {
  document.getElementById('main-nav').classList.toggle('open');
}

// ─── Détecter le niveau de la page ───────────────────────
const path = window.location.pathname;
const isSecondaire = path.includes('/secondaires/');
const isBlog = path.includes('/blog/');
const isPilier = path.includes('/piliers/');
let prefix = '';
if (isSecondaire) prefix = '../../';
else if (isBlog || isPilier) prefix = '../';

// ─── Charger les articles JSON ────────────────────────────
fetch(prefix + 'articles.json')
  .then(r => r.json())
  .then(articles => {

    // Articles récents sidebar
    const widgetRecents = document.getElementById('widget-recents');
    if (widgetRecents) {
      widgetRecents.innerHTML = '<h3>Articles récents</h3>';
      articles.slice(0, 6).forEach(art => {
        const a = document.createElement('a');
        a.href = prefix + 'blog/' + art.slug + '.html';
        a.textContent = art.titre;
        widgetRecents.appendChild(a);
      });
    }

    // Grille articles page d'accueil
    const gridAccueil = document.getElementById('grid-articles');
    if (gridAccueil) {
      articles.slice(0, 6).forEach(art => {
        const thumb = art.thumb ? `<img src="blog/${art.slug}/../../../${art.thumb}" class="card-image" alt="${art.titre}">` : '';
        gridAccueil.innerHTML += `
          <a href="blog/${art.slug}.html" class="article-card">
            ${art.thumb ? `<img src="${art.thumb}" class="card-image" alt="${art.titre}">` : ''}
            <div class="card-body">
              <span class="categorie">${art.categorie}</span>
              <h2>${art.titre}</h2>
              <p>${art.description.substring(0, 100)}...</p>
            </div>
          </a>`;
      });
    }

    // Articles blog dans page pilier
    const pilierId = typeof PILIER_ID !== 'undefined' ? PILIER_ID : null;
    const gridBlog = pilierId ? document.getElementById('grid-blog-' + pilierId) : null;
    if (gridBlog) {
      const filtres = articles.filter(a => a.pilier_id === pilierId).slice(0, 6);
      filtres.forEach(art => {
        gridBlog.innerHTML += `
          <a href="../blog/${art.slug}.html" class="article-card">
            ${art.thumb ? `<img src="${art.thumb}" class="card-image" alt="${art.titre}">` : ''}
            <div class="card-body">
              <span class="categorie">${art.categorie}</span>
              <h2>${art.titre}</h2>
              <p>${art.description.substring(0, 100)}...</p>
            </div>
          </a>`;
      });
    }

    // Articles connexes dans page secondaire
    const blogConnexes = document.getElementById('blog-connexes');
    if (blogConnexes && pilierId) {
      const pageSlug = typeof PAGE_SLUG !== 'undefined' ? PAGE_SLUG : '';
      const filtres = articles
        .filter(a => a.pilier_id === pilierId || a.secondaire_slug === pageSlug)
        .slice(0, 3);
      filtres.forEach(art => {
        blogConnexes.innerHTML += `
          <a href="../../blog/${art.slug}.html" class="connexe-card">
            ${art.thumb ? `<img src="${art.thumb}" alt="${art.titre}">` : ''}
            <div class="connexe-card-body"><h3>${art.titre}</h3></div>
          </a>`;
      });
    }

  })
  .catch(() => {});
