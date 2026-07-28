# Производительность ArtFlowWeb

Полный измеренный baseline, итоговое сравнение и действующие бюджеты находятся в
[`docs/performance-budget.md`](performance-budget.md).

Текущий статический профиль без сжатия:

- `main.js` — 10 303 bytes;
- CSS суммарно — 58 821 bytes в четырёх файлах;
- `hero-main-960.webp` — 51 584 bytes;
- `hero-main.webp` — 101 120 bytes;
- `artflow-logo-512.png` — 61 474 bytes.

Контролируемые изображения используют WebP responsive variants, явные `width` и
`height`, `srcset`/`sizes`, eager только выше первого экрана и lazy ниже него.
Подтверждённые Playwright LCP-изображения каталога и FAQ, а также основной hero
главной имеют высокий fetch priority; карточки и остальные изображения его не
получают.

Приложение gzip-сжимает достаточно большие HTML, CSS, JavaScript, XML и JSON,
но пропускает уже сжатые изображения, PDF, архивы, видео и web fonts.
Версионированные CSS/JS кешируются на год как immutable, остальные локальные assets
— на сутки со stale revalidation. `ETag` и `Last-Modified` сохраняются.

Повторяемый локальный аудит:

```powershell
python -m scripts.performance_audit audit --base-url http://127.0.0.1:8000 --json-output dist/performance.json --markdown-output dist/performance.md
python -m scripts.performance_audit structural-checks --report dist/performance.json
python -m scripts.performance_audit compare dist/before.json dist/after.json --fail-on-regression --markdown-output dist/compare.md
```

Это лабораторные Playwright-метрики, а не полевые Core Web Vitals. После deployment
владелец отдельно запускает PageSpeed Insights и проверяет реальные данные Google
Search Console. Lighthouse не установлен и не добавлен как новый Node.js toolchain.
