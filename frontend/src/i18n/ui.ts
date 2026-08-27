// #106: UI translation dictionaries. `ui.en` is the source-of-truth key
// set — every other locale is checked against it (see i18n.test.ts) and
// falls back to the English string at runtime for anything missing (see
// utils.ts's t()), rather than showing a raw key or throwing, so a
// partial translation never breaks rendering.
//
// Deliberately does NOT cover: filler/canon status text written by
// contributors (status_note, citation.description/methodology_note),
// series/episode titles, or anything else that's cited, sourced content
// rather than this app's own UI chrome — see #106's own scope note and
// CLAUDE.md Data Source for why translating that would misrepresent what
// a citation actually says.
//
// Pluralized strings use an explicit "_one"/"_other" key pair rather than
// a plural-rules library (Intl.PluralRules) — genuinely overkill for a
// first cut with only a handful of pluralized strings, matching this
// project's general bias against building for demand that doesn't exist
// yet. Japanese and Chinese have no plural forms, so both keys just hold
// the identical string in those two locale files.

export const SUPPORTED_LOCALES = ["en", "es", "hi", "ja", "zh-cn"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en";

// Each language's own name for itself, for the language switcher — not
// translated per-locale, since a language name is most recognizable in
// its own script (same convention as AniDex's own LOCALE_LABELS).
export const LOCALE_LABELS: Record<Locale, string> = {
  en: "English",
  es: "Español",
  hi: "हिन्दी",
  ja: "日本語",
  "zh-cn": "简体中文",
};

const en = {
  "nav.browse": "Browse",
  "nav.reviewQueue": "Review queue",
  "nav.manageUsers": "Manage users",
  "nav.account": "Account",
  "nav.logOut": "Log out",
  "nav.logInGithub": "Log in with GitHub",
  "nav.logInDiscord": "Discord",

  "footer.license": "License",
  "footer.privacy": "Privacy",

  "meta.defaultDescription":
    "AniFillerPedia is an open, community-editable database of anime filler and canon episodes — find out which episodes you can skip, and which you can't.",

  "home.title": "AniFillerPedia — Browse anime filler & canon guides",
  "home.description":
    "Free, community-edited filler and canon episode guides for anime — Naruto, Bleach, One Piece, Fairy Tail, and more. See exactly which episodes to skip and which adapt the real story, every claim cited.",
  "home.headline": "Know what's canon<br />before you watch!",
  "home.tagline": "Built by fans, checked by fans — cited every step of the way.",
  "home.proposeCta.strong": "Something's missing?",
  "home.proposeCta.rest": "Add it here — just a name, and an AniList ID if you have one.",
  "home.reviewTeaser.pending_one": "{count} contribution pending review",
  "home.reviewTeaser.pending_other": "{count} contributions pending review",
  "home.recentlyUpdated": "Recently updated",
  "home.resultsFor": 'Results for "{q}"',
  "home.allSeries": "All series",
  "home.seriesFound_one": "{count} series found",
  "home.seriesFound_other": "{count} series found",
  "home.loadError": "Couldn't load series right now — try again shortly.",
  "home.noMatch": 'No series match "{q}" yet — maybe propose it?',
  "home.emptyCatalog": "No series in the catalog yet.",
  "home.pagination.prev": "← Prev",
  "home.pagination.next": "Next →",
  "home.pagination.status": "Page {page} of {totalPages}",
  "home.searchPlaceholder": "Search Naruto, Bleach, One Piece...",
  "home.pagination.ariaLabel": "Series pagination",

  "series.notFound.title": "Series not found",
  "series.notFound.body": "There's no series with that id in AniFillerPedia yet.",
  "series.notFound.back": "← Back to browse",
  "series.alsoKnownAs": "Also known as ({count})",
  "series.alsoOnThisSite": "Also on this site:",
  "series.status.canon": "Canon",
  "series.status.filler": "Filler",
  "series.status.mixed": "Mixed",
  "series.pctOfTracked": "{pct}% of tracked",
  "series.episodesTracked_one": "{count} episode tracked",
  "series.episodesTracked_other": "{count} episodes tracked",
  "series.episodesTrackedOf": "{count} of {total} episodes tracked",
  "series.filterChip.showing": "Showing:",
  "series.filterChip.episodesOnly": "episodes only",
  "series.filterChip.clear": "✕ clear",
  "series.empty.title": "No episodes researched yet",
  "series.empty.body": "Nobody has submitted filler/canon data for this series yet — be the first.",
  "series.empty.submitFirst": "Submit episode 1",
  "series.episodeAbbrev": "Ep. {number}",
  "series.sourcesAgree": "{count} independent sources agree",
  "series.lastVerified": "Last verified {date}",
  "series.historyAndVotes": "History & votes",
  "series.submitCorrection": "Submit correction",
  "series.howVerified": "How was this verified?",
  "series.pageTitle.found": "{title} — AniFillerPedia",
  "series.pageTitle.notFound": "Series not found — AniFillerPedia",
  "series.pageDescription.withEpisodes":
    "{title} filler episode guide — {count} episodes tracked, {pct}% canon. See exactly which episodes to skip, every claim cited.",
  "series.pageDescription.withEpisodesOfTotal":
    "{title} filler episode guide — {count} of {total} episodes tracked, {pct}% canon. See exactly which episodes to skip, every claim cited.",
  "series.pageDescription.empty":
    "{title} on AniFillerPedia — no episodes researched yet. Help build the filler/canon guide for this series.",
  "series.pendingIndicator.title": "Has a pending correction under review",
  "series.pendingIndicator.label": "Pending",
  "series.airingBadge": "Airing",
  // #126: about-card label/toggle + era-tile date-range framing. The
  // description text itself stays English-only (sourced content, not UI
  // chrome — see #106's own scope note), only this chrome is translated.
  "series.about.label": "About",
  "series.about.readMore": "Read more",
  "series.era.range": "{startYear} – {endYear}",
  "series.era.ongoing": "{startYear} – present",
  // #133: within-franchise watch-order navigation (e.g. "Also on this
  // site" links tell you a related entry exists; these are the stronger
  // "go watch it" call-to-action pointing at the adjacent entry in watch
  // order specifically). Only rendered when the series has an adjacent
  // entry — see SeriesDetailPage.astro's watch-nav block.
  "series.watchPrevious": "Watch previous",
  "series.watchNext": "Watch next",

  "lang.switcher.label": "Language",
};

export type TranslationKey = keyof typeof en;

const es: Partial<Record<TranslationKey, string>> = {
  "nav.browse": "Explorar",
  "nav.reviewQueue": "Cola de revisión",
  "nav.manageUsers": "Gestionar usuarios",
  "nav.account": "Cuenta",
  "nav.logOut": "Cerrar sesión",
  "nav.logInGithub": "Iniciar sesión con GitHub",
  "nav.logInDiscord": "Discord",

  "footer.license": "Licencia",
  "footer.privacy": "Privacidad",

  "meta.defaultDescription":
    "AniFillerPedia es una base de datos abierta y editable por la comunidad sobre episodios de relleno y canon de anime — descubre qué episodios puedes saltarte y cuáles no.",

  "home.title": "AniFillerPedia — Guías de relleno y canon de anime",
  "home.description":
    "Guías gratuitas y editadas por la comunidad sobre episodios de relleno y canon de anime — Naruto, Bleach, One Piece, Fairy Tail y más. Descubre exactamente qué episodios saltarte y cuáles siguen la historia real, con cada afirmación citada.",
  "home.headline": "Descubre qué es canon<br />antes de verlo!",
  "home.tagline": "Hecho por fans, verificado por fans — con citas en cada paso.",
  "home.proposeCta.strong": "¿Falta algo?",
  "home.proposeCta.rest": "Añádelo aquí — solo un nombre, y un ID de AniList si lo tienes.",
  "home.reviewTeaser.pending_one": "{count} contribución pendiente de revisión",
  "home.reviewTeaser.pending_other": "{count} contribuciones pendientes de revisión",
  "home.recentlyUpdated": "Actualizado recientemente",
  "home.resultsFor": 'Resultados para "{q}"',
  "home.allSeries": "Todas las series",
  "home.seriesFound_one": "{count} serie encontrada",
  "home.seriesFound_other": "{count} series encontradas",
  "home.loadError": "No se pudieron cargar las series — inténtalo de nuevo en breve.",
  "home.noMatch": '¿Ninguna serie coincide con "{q}" todavía — quieres proponerla?',
  "home.emptyCatalog": "Todavía no hay series en el catálogo.",
  "home.pagination.prev": "← Anterior",
  "home.pagination.next": "Siguiente →",
  "home.pagination.status": "Página {page} de {totalPages}",
  "home.searchPlaceholder": "Busca Naruto, Bleach, One Piece...",
  "home.pagination.ariaLabel": "Paginación de series",

  "series.notFound.title": "Serie no encontrada",
  "series.notFound.body": "No hay ninguna serie con ese id en AniFillerPedia todavía.",
  "series.notFound.back": "← Volver a explorar",
  "series.alsoKnownAs": "También conocido como ({count})",
  "series.alsoOnThisSite": "También en este sitio:",
  "series.status.canon": "Canon",
  "series.status.filler": "Relleno",
  "series.status.mixed": "Mixto",
  "series.pctOfTracked": "{pct}% de lo registrado",
  "series.episodesTracked_one": "{count} episodio registrado",
  "series.episodesTracked_other": "{count} episodios registrados",
  "series.episodesTrackedOf": "{count} de {total} episodios registrados",
  "series.filterChip.showing": "Mostrando:",
  "series.filterChip.episodesOnly": "episodios solamente",
  "series.filterChip.clear": "✕ borrar",
  "series.empty.title": "Aún no se ha investigado ningún episodio",
  "series.empty.body": "Nadie ha enviado datos de relleno/canon para esta serie todavía — sé el primero.",
  "series.empty.submitFirst": "Enviar episodio 1",
  "series.episodeAbbrev": "Ep. {number}",
  "series.sourcesAgree": "{count} fuentes independientes coinciden",
  "series.lastVerified": "Última verificación {date}",
  "series.historyAndVotes": "Historial y votos",
  "series.submitCorrection": "Enviar corrección",
  "series.howVerified": "¿Cómo se verificó esto?",
  "series.pageTitle.found": "{title} — AniFillerPedia",
  "series.pageTitle.notFound": "Serie no encontrada — AniFillerPedia",
  "series.pageDescription.withEpisodes":
    "Guía de episodios de relleno de {title} — {count} episodios registrados, {pct}% canon. Descubre exactamente qué episodios saltarte, con cada afirmación citada.",
  "series.pageDescription.withEpisodesOfTotal":
    "Guía de episodios de relleno de {title} — {count} de {total} episodios registrados, {pct}% canon. Descubre exactamente qué episodios saltarte, con cada afirmación citada.",
  "series.pageDescription.empty":
    "{title} en AniFillerPedia — aún no se ha investigado ningún episodio. Ayuda a construir la guía de relleno/canon para esta serie.",
  "series.pendingIndicator.title": "Tiene una corrección pendiente de revisión",
  "series.pendingIndicator.label": "Pendiente",
  "series.airingBadge": "En emisión",
  "series.about.label": "Acerca de",
  "series.about.readMore": "Leer más",
  "series.era.range": "{startYear} – {endYear}",
  "series.era.ongoing": "{startYear} – presente",
  "series.watchPrevious": "Ver anterior",
  "series.watchNext": "Ver siguiente",

  "lang.switcher.label": "Idioma",
};

const hi: Partial<Record<TranslationKey, string>> = {
  "nav.browse": "ब्राउज़ करें",
  "nav.reviewQueue": "समीक्षा सूची",
  "nav.manageUsers": "उपयोगकर्ता प्रबंधित करें",
  "nav.account": "खाता",
  "nav.logOut": "लॉग आउट करें",
  "nav.logInGithub": "GitHub से लॉग इन करें",
  "nav.logInDiscord": "Discord",

  "footer.license": "लाइसेंस",
  "footer.privacy": "गोपनीयता",

  "meta.defaultDescription":
    "AniFillerPedia एनीमे के फिलर और कैनन एपिसोड की एक खुली, समुदाय-संपादनीय डेटाबेस है — जानें कौन-से एपिसोड छोड़े जा सकते हैं और कौन-से नहीं।",

  "home.title": "AniFillerPedia — एनीमे फिलर और कैनन गाइड ब्राउज़ करें",
  "home.description":
    "एनीमे के लिए मुफ़्त, समुदाय-संपादित फिलर और कैनन एपिसोड गाइड — नारुतो, ब्लीच, वन पीस, फेयरी टेल, और अन्य। जानें कौन-से एपिसोड छोड़े जा सकते हैं और कौन-से असली कहानी को आगे बढ़ाते हैं, हर दावे के स्रोत सहित।",
  "home.headline": "देखने से पहले जानें<br />क्या कैनन है!",
  "home.tagline": "प्रशंसकों द्वारा बनाया गया, प्रशंसकों द्वारा जाँचा गया — हर कदम पर स्रोत के साथ।",
  "home.proposeCta.strong": "कुछ छूट रहा है?",
  "home.proposeCta.rest": "इसे यहाँ जोड़ें — बस एक नाम, और यदि आपके पास हो तो एक AniList ID।",
  "home.reviewTeaser.pending_one": "{count} योगदान समीक्षा हेतु लंबित",
  "home.reviewTeaser.pending_other": "{count} योगदान समीक्षा हेतु लंबित",
  "home.recentlyUpdated": "हाल ही में अपडेट किया गया",
  "home.resultsFor": '"{q}" के लिए परिणाम',
  "home.allSeries": "सभी सीरीज़",
  "home.seriesFound_one": "{count} सीरीज़ मिली",
  "home.seriesFound_other": "{count} सीरीज़ मिलीं",
  "home.loadError": "अभी सीरीज़ लोड नहीं हो सकीं — कृपया थोड़ी देर बाद फिर से प्रयास करें।",
  "home.noMatch": '"{q}" से कोई सीरीज़ मेल नहीं खाती — इसे प्रस्तावित करना चाहेंगे?',
  "home.emptyCatalog": "कैटलॉग में अभी तक कोई सीरीज़ नहीं है।",
  "home.pagination.prev": "← पिछला",
  "home.pagination.next": "अगला →",
  "home.pagination.status": "पृष्ठ {page} / {totalPages}",
  "home.searchPlaceholder": "नारुतो, ब्लीच, वन पीस खोजें...",
  "home.pagination.ariaLabel": "सीरीज़ पेजिनेशन",

  "series.notFound.title": "सीरीज़ नहीं मिली",
  "series.notFound.body": "AniFillerPedia में अभी तक इस id वाली कोई सीरीज़ नहीं है।",
  "series.notFound.back": "← ब्राउज़ पर वापस जाएँ",
  "series.alsoKnownAs": "अन्य नाम ({count})",
  "series.alsoOnThisSite": "इस साइट पर भी:",
  "series.status.canon": "कैनन",
  "series.status.filler": "फिलर",
  "series.status.mixed": "मिश्रित",
  "series.pctOfTracked": "दर्ज का {pct}%",
  "series.episodesTracked_one": "{count} एपिसोड दर्ज",
  "series.episodesTracked_other": "{count} एपिसोड दर्ज",
  "series.episodesTrackedOf": "{total} में से {count} एपिसोड दर्ज",
  "series.filterChip.showing": "दिखा रहे हैं:",
  "series.filterChip.episodesOnly": "एपिसोड ही",
  "series.filterChip.clear": "✕ हटाएँ",
  "series.empty.title": "अभी तक किसी एपिसोड पर शोध नहीं हुआ",
  "series.empty.body": "इस सीरीज़ के लिए अभी तक किसी ने फिलर/कैनन डेटा जमा नहीं किया — सबसे पहले आप बनें।",
  "series.empty.submitFirst": "एपिसोड 1 जमा करें",
  "series.episodeAbbrev": "एपि. {number}",
  "series.sourcesAgree": "{count} स्वतंत्र स्रोत सहमत हैं",
  "series.lastVerified": "अंतिम सत्यापन {date}",
  "series.historyAndVotes": "इतिहास और वोट",
  "series.submitCorrection": "सुधार जमा करें",
  "series.howVerified": "इसे कैसे सत्यापित किया गया?",
  "series.pageTitle.found": "{title} — AniFillerPedia",
  "series.pageTitle.notFound": "सीरीज़ नहीं मिली — AniFillerPedia",
  "series.pageDescription.withEpisodes":
    "{title} फिलर एपिसोड गाइड — {count} एपिसोड दर्ज, {pct}% कैनन। जानें कौन-से एपिसोड छोड़े जा सकते हैं, हर दावे के स्रोत सहित।",
  "series.pageDescription.withEpisodesOfTotal":
    "{title} फिलर एपिसोड गाइड — {total} में से {count} एपिसोड दर्ज, {pct}% कैनन। जानें कौन-से एपिसोड छोड़े जा सकते हैं, हर दावे के स्रोत सहित।",
  "series.pageDescription.empty":
    "AniFillerPedia पर {title} — अभी तक किसी एपिसोड पर शोध नहीं हुआ। इस सीरीज़ के लिए फिलर/कैनन गाइड बनाने में मदद करें।",
  "series.pendingIndicator.title": "समीक्षाधीन एक लंबित सुधार है",
  "series.pendingIndicator.label": "लंबित",
  "series.airingBadge": "प्रसारणाधीन",
  "series.about.label": "परिचय",
  "series.about.readMore": "और पढ़ें",
  "series.era.range": "{startYear} – {endYear}",
  "series.era.ongoing": "{startYear} – अब तक",
  "series.watchPrevious": "पिछला देखें",
  "series.watchNext": "अगला देखें",

  "lang.switcher.label": "भाषा",
};

const ja: Partial<Record<TranslationKey, string>> = {
  "nav.browse": "閲覧",
  "nav.reviewQueue": "レビュー待ち一覧",
  "nav.manageUsers": "ユーザー管理",
  "nav.account": "アカウント",
  "nav.logOut": "ログアウト",
  "nav.logInGithub": "GitHubでログイン",
  "nav.logInDiscord": "Discord",

  "footer.license": "ライセンス",
  "footer.privacy": "プライバシー",

  "meta.defaultDescription":
    "AniFillerPediaは、アニメのフィラー回とカノン回を誰でも編集できるオープンなデータベースです — どの回を飛ばせて、どの回は飛ばせないかがわかります。",

  "home.title": "AniFillerPedia — アニメのフィラー・カノンガイドを閲覧",
  "home.description":
    "ナルト、BLEACH、ワンピース、フェアリーテイルなど、アニメのフィラー・カノン回ガイドを無料でコミュニティが編集。どの回を飛ばせて、どの回が本編に沿っているかが一目でわかり、すべての情報に出典があります。",
  "home.headline": "見る前に、何がカノンか<br />知っておこう！",
  "home.tagline": "ファンによって作られ、ファンによって検証された — すべての情報に出典付き。",
  "home.proposeCta.strong": "作品が見つかりませんか？",
  "home.proposeCta.rest": "ここから追加できます — 名前だけでOK、AniList IDがあればなお良し。",
  "home.reviewTeaser.pending_one": "{count}件の投稿がレビュー待ちです",
  "home.reviewTeaser.pending_other": "{count}件の投稿がレビュー待ちです",
  "home.recentlyUpdated": "最近更新された作品",
  "home.resultsFor": "「{q}」の検索結果",
  "home.allSeries": "すべての作品",
  "home.seriesFound_one": "{count}件の作品が見つかりました",
  "home.seriesFound_other": "{count}件の作品が見つかりました",
  "home.loadError": "作品を読み込めませんでした — しばらくしてからもう一度お試しください。",
  "home.noMatch": "「{q}」に一致する作品はまだありません — 追加を提案しますか？",
  "home.emptyCatalog": "カタログにはまだ作品がありません。",
  "home.pagination.prev": "← 前へ",
  "home.pagination.next": "次へ →",
  "home.pagination.status": "{page} / {totalPages} ページ",
  "home.searchPlaceholder": "ナルト、BLEACH、ワンピースを検索...",
  "home.pagination.ariaLabel": "作品一覧のページ送り",

  "series.notFound.title": "作品が見つかりません",
  "series.notFound.body": "このIDの作品はAniFillerPediaにまだ登録されていません。",
  "series.notFound.back": "← 閲覧に戻る",
  "series.alsoKnownAs": "別名（{count}件）",
  "series.alsoOnThisSite": "このサイトの関連作品：",
  "series.status.canon": "カノン",
  "series.status.filler": "フィラー",
  "series.status.mixed": "混合",
  "series.pctOfTracked": "登録済みの{pct}%",
  "series.episodesTracked_one": "{count}話を登録済み",
  "series.episodesTracked_other": "{count}話を登録済み",
  "series.episodesTrackedOf": "全{total}話中{count}話を登録済み",
  "series.filterChip.showing": "表示中：",
  "series.filterChip.episodesOnly": "の話のみ",
  "series.filterChip.clear": "✕ 解除",
  "series.empty.title": "まだ調査された話がありません",
  "series.empty.body": "この作品のフィラー・カノン情報はまだ誰も投稿していません — 最初の投稿者になりましょう。",
  "series.empty.submitFirst": "第1話を投稿する",
  "series.episodeAbbrev": "第{number}話",
  "series.sourcesAgree": "{count}件の独立した情報源が一致",
  "series.lastVerified": "最終確認：{date}",
  "series.historyAndVotes": "履歴と投票",
  "series.submitCorrection": "修正を投稿",
  "series.howVerified": "どのように検証されましたか？",
  "series.pageTitle.found": "{title} — AniFillerPedia",
  "series.pageTitle.notFound": "作品が見つかりません — AniFillerPedia",
  "series.pageDescription.withEpisodes":
    "{title} フィラーエピソードガイド — {count}話を登録済み、{pct}%がカノン。どの回を飛ばせるか一目でわかり、すべての情報に出典があります。",
  "series.pageDescription.withEpisodesOfTotal":
    "{title} フィラーエピソードガイド — 全{total}話中{count}話を登録済み、{pct}%がカノン。どの回を飛ばせるか一目でわかり、すべての情報に出典があります。",
  "series.pageDescription.empty":
    "AniFillerPediaの{title} — まだ調査された話がありません。この作品のフィラー・カノンガイド作りに協力してください。",
  "series.pendingIndicator.title": "審査中の修正提案があります",
  "series.pendingIndicator.label": "審査中",
  "series.airingBadge": "放送中",
  "series.about.label": "概要",
  "series.about.readMore": "続きを読む",
  "series.era.range": "{startYear} – {endYear}",
  "series.era.ongoing": "{startYear} – 放送中",
  "series.watchPrevious": "前作を見る",
  "series.watchNext": "次作を見る",

  "lang.switcher.label": "言語",
};

const zhCN: Partial<Record<TranslationKey, string>> = {
  "nav.browse": "浏览",
  "nav.reviewQueue": "审核队列",
  "nav.manageUsers": "管理用户",
  "nav.account": "账户",
  "nav.logOut": "退出登录",
  "nav.logInGithub": "使用 GitHub 登录",
  "nav.logInDiscord": "Discord",

  "footer.license": "许可协议",
  "footer.privacy": "隐私政策",

  "meta.defaultDescription":
    "AniFillerPedia 是一个开放的、可由社区编辑的动漫填充集与原著集数据库 — 让你知道哪些集数可以跳过，哪些不能。",

  "home.title": "AniFillerPedia — 浏览动漫填充与原著剧情指南",
  "home.description":
    "免费的、由社区编辑的动漫填充集与原著集指南 —— 火影忍者、死神、海贼王、妖精的尾巴等。准确了解哪些集数可以跳过，哪些真正推进原著剧情，每一条信息都附有来源。",
  "home.headline": "开始观看前<br />先了解什么是原著剧情！",
  "home.tagline": "由粉丝制作，由粉丝核实 —— 每一步都有据可查。",
  "home.proposeCta.strong": "找不到你想要的作品？",
  "home.proposeCta.rest": "在这里添加它 —— 只需名称，如果有 AniList ID 就更好了。",
  "home.reviewTeaser.pending_one": "{count} 条贡献待审核",
  "home.reviewTeaser.pending_other": "{count} 条贡献待审核",
  "home.recentlyUpdated": "最近更新",
  "home.resultsFor": "“{q}” 的搜索结果",
  "home.allSeries": "全部作品",
  "home.seriesFound_one": "找到 {count} 部作品",
  "home.seriesFound_other": "找到 {count} 部作品",
  "home.loadError": "暂时无法加载作品列表 —— 请稍后重试。",
  "home.noMatch": "暂无与“{q}”匹配的作品 —— 要不要提交添加申请？",
  "home.emptyCatalog": "目录中暂无任何作品。",
  "home.pagination.prev": "← 上一页",
  "home.pagination.next": "下一页 →",
  "home.pagination.status": "第 {page} / {totalPages} 页",
  "home.searchPlaceholder": "搜索火影忍者、死神、海贼王...",
  "home.pagination.ariaLabel": "作品分页",

  "series.notFound.title": "未找到该作品",
  "series.notFound.body": "AniFillerPedia 中还没有该 ID 对应的作品。",
  "series.notFound.back": "← 返回浏览",
  "series.alsoKnownAs": "别名（{count}）",
  "series.alsoOnThisSite": "本站相关作品：",
  "series.status.canon": "原著",
  "series.status.filler": "填充",
  "series.status.mixed": "混合",
  "series.pctOfTracked": "占已收录的 {pct}%",
  "series.episodesTracked_one": "已收录 {count} 集",
  "series.episodesTracked_other": "已收录 {count} 集",
  "series.episodesTrackedOf": "已收录 {total} 集中的 {count} 集",
  "series.filterChip.showing": "正在显示：",
  "series.filterChip.episodesOnly": "的集数",
  "series.filterChip.clear": "✕ 清除",
  "series.empty.title": "尚未有任何集数经过研究",
  "series.empty.body": "还没有人为这部作品提交填充/原著数据 —— 来做第一个提交的人吧。",
  "series.empty.submitFirst": "提交第 1 集",
  "series.episodeAbbrev": "第 {number} 集",
  "series.sourcesAgree": "{count} 个独立来源一致认可",
  "series.lastVerified": "最后核实于 {date}",
  "series.historyAndVotes": "历史记录与投票",
  "series.submitCorrection": "提交更正",
  "series.howVerified": "这是如何核实的？",
  "series.pageTitle.found": "{title} — AniFillerPedia",
  "series.pageTitle.notFound": "未找到该作品 — AniFillerPedia",
  "series.pageDescription.withEpisodes":
    "{title} 填充集指南 —— 已收录 {count} 集，{pct}% 为原著剧情。准确了解哪些集数可以跳过，每一条信息都附有来源。",
  "series.pageDescription.withEpisodesOfTotal":
    "{title} 填充集指南 —— 已收录 {total} 集中的 {count} 集，{pct}% 为原著剧情。准确了解哪些集数可以跳过，每一条信息都附有来源。",
  "series.pageDescription.empty":
    "AniFillerPedia 上的 {title} —— 尚未有任何集数经过研究。帮助我们为这部作品建立填充/原著指南。",
  "series.pendingIndicator.title": "有一个待审核的更正",
  "series.pendingIndicator.label": "待处理",
  "series.airingBadge": "连载中",
  "series.about.label": "简介",
  "series.about.readMore": "阅读更多",
  "series.era.range": "{startYear} – {endYear}",
  "series.era.ongoing": "{startYear} – 至今",
  "series.watchPrevious": "观看上一部",
  "series.watchNext": "观看下一部",

  "lang.switcher.label": "语言",
};

export const ui: Record<Locale, Partial<Record<TranslationKey, string>>> = {
  en,
  es,
  hi,
  ja,
  "zh-cn": zhCN,
};
