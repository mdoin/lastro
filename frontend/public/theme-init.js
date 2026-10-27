// Aplica o tema escolhido (claro/escuro) antes da primeira pintura, para não piscar o tema errado.
// Arquivo externo de propósito: a CSP do app (script-src 'self') não permite script inline.
// Mesma chave e mesmas cores de src/lib/theme.ts.
(function () {
  try {
    var t = window.localStorage.getItem("lastro.theme");
    if (t !== "light" && t !== "dark") return;
    document.documentElement.setAttribute("data-theme", t);
    var color = t === "dark" ? "#0b0b0a" : "#f4f4f2";
    var metas = document.querySelectorAll('meta[name="theme-color"]');
    for (var i = 0; i < metas.length; i++) metas[i].setAttribute("content", color);
  } catch (e) {
    /* sem armazenamento: segue o tema do aparelho */
  }
})();
