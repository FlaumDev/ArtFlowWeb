# Performance budget ArtFlowWeb

## Методика измерения

Baseline снят 28 июля 2026 года до runtime-оптимизаций, итоговый замер — после
них. Использовались Chromium через уже установленный Python Playwright и локальное
mock-приложение `tests.e2e.mock_app`, не подключённое к PostgreSQL, Telegram или
production.

Условия обоих замеров:

- viewport `375x812`, mobile context, device scale factor `1`;
- новый browser context для каждого холодного открытия страницы;
- одинаковый локальный origin `http://127.0.0.1:8765`;
- сторонние ресурсы заблокированы;
- Navigation Timing, Resource Timing, LCP и layout-shift через браузерные API;
- menu, FAQ и фильтр каталога проверяются реальными взаимодействиями;
- без искусственного network/CPU throttling.

Baseline использует медиану трёх runs, итоговый отчёт — медиану пяти. Это
лабораторные данные конкретного компьютера, не полевые Core Web Vitals и не
результат Lighthouse. Node.js и Lighthouse в проекте не установлены, поэтому они
не добавлялись только ради этой проверки.

## Измеренный baseline

До оптимизации HTML, CSS и JavaScript передавались без gzip. `StaticFiles`
возвращал `ETag` и `Last-Modified`, но не задавал `Cache-Control`.

| Path | TTFB, ms | DCL, ms | Load, ms | LCP, ms | CLS | HTML, B | Transfer, B | Requests | DOM nodes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `/` | 18.3 | 279.8 | 288.9 | 292 | 0 | 49 088 | 307 520 | 11 | 443 |
| `/competitions` | 14.4 | 237.2 | 250.5 | 240 | 0 | 29 981 | 288 413 | 11 | 279 |
| `/competitions/7` | 12.4 | 224.5 | 226.1 | 236 | 0 | 27 529 | 197 999 | 9 | 264 |
| `/faq` | 11.8 | 146.3 | 150.0 | 160 | 0 | 14 615 | 196 086 | 8 | 138 |
| `/about` | 14.4 | 180.7 | 184.8 | 188 | 0 | 21 439 | 154 142 | 7 | 194 |
| `/how-to-participate` | 13.6 | 205.1 | 208.3 | 220 | 0 | 21 398 | 154 101 | 7 | 209 |

Статический baseline без сжатия:

- собственный JavaScript: 1 файл, `10 400` bytes;
- собственный CSS: 4 файла, `58 729` bytes;
- локальные изображения: 24 файла, `1 960 902` bytes;
- используемый fallback/logo: `61 474` bytes;
- mobile hero variant `hero-main-960.webp`: `51 584` bytes.

На baseline кандидаты LCP были текстовыми на всех шести страницах. Главный
заголовок hero при этом скрывался до `DOMContentLoaded` и двух следующих animation
frames, поэтому зависел от выполнения JavaScript.

## Результат после оптимизации

| Path | TTFB, ms | DCL, ms | Load, ms | LCP, ms | CLS | HTML, B | Transfer, B | Delta transfer | Requests |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `/` | 17.8 | 289.7 | 304.8 | 304 | 0 | 49 093 | 212 312 | -31.0% | 11 |
| `/competitions` | 17.7 | 235.6 | 241.8 | 252 | 0 | 30 007 | 209 565 | -27.3% | 11 |
| `/competitions/7` | 16.3 | 251.9 | 258.9 | 256 | 0 | 27 534 | 121 386 | -38.7% | 9 |
| `/faq` | 14.6 | 169.7 | 172.9 | 196 | 0 | 14 641 | 130 381 | -33.5% | 8 |
| `/about` | 15.1 | 199.9 | 204.0 | 208 | 0 | 21 444 | 82 570 | -46.4% | 7 |
| `/how-to-participate` | 13.7 | 190.8 | 209.3 | 216 | 0 | 21 403 | 82 596 | -46.4% | 7 |

Подтверждённые изменения:

- CSS transfer на каждой странице уменьшился с `59 929` до `13 844` bytes;
- JavaScript transfer уменьшился с `10 700` до `2 666` bytes;
- общий transfer уменьшился на `27-46%` без новых запросов;
- `CLS` остался равен `0`, DOM и число запросов не изменились;
- hero больше не скрывается до запуска JavaScript;
- в пяти из пяти итоговых runs LCP каталога был `hero-main-960.webp`, а LCP FAQ —
  `about-project-960.webp`; только эти два изображения дополнительно получили
  `fetchpriority="high"`.

Абсолютные локальные LCP/TTFB колеблются и местами стали выше: на loopback нет
выигрыша от меньшего network transfer, но остаётся CPU-стоимость gzip. Поэтому эти
замеры подтверждают экономию трафика и стабильный layout, но не доказывают
улучшение полевых LCP или INP. После deployment нужны PageSpeed Insights и данные
реальных пользователей.

## Бюджет

| Ресурс или метрика | Бюджет |
|---|---:|
| Собственный JavaScript без сжатия | не более 25 KiB |
| Собственный CSS без сжатия | не более 75 KiB |
| Декодированный HTML одной основной страницы | не более 100 KiB |
| Собственные JavaScript-файлы | не более 1 |
| Собственные CSS-файлы | не более 4 |
| Requests на основной странице mock-набора | не более 30 |
| DOM nodes | не более 1 200 |
| Локальный fallback/logo | не более 75 KiB |
| Mobile hero variant | не более 150 KiB |
| LCP p75 mobile, полевая цель | не более 2.5 s |
| INP p75, полевая цель | не более 200 ms |
| CLS p75, полевая цель | не более 0.1 |

`structural-checks` жёстко проверяет детерминированные размеры, количество файлов,
DOM, requests, размеры `<img>`, синхронные scripts, overflow и console errors.
`compare --fail-on-regression` завершает команду ошибкой, если HTML, общий transfer,
CSS, JavaScript, requests или DOM в сопоставимом mock-замере выросли более чем на
10%. Точные временные показатели намеренно не являются unit-test assertion.

## Правила загрузки ресурсов

- подтверждённое LCP-изображение первого экрана использует `loading="eager"`,
  `fetchpriority="high"`, `decoding="async"`, `width`, `height`, `srcset` и `sizes`;
- изображения ниже первого экрана используют `loading="lazy"` и
  `decoding="async"`;
- secondary image может оставаться lazy, пока измерения не подтверждают его как LCP;
- карточки и внешние афиши не получают высокий fetch priority;
- CSS/JS имеют query version и cache policy
  `public, max-age=31536000, immutable`;
- остальная локальная статика получает `max-age=86400` и
  `stale-while-revalidate=604800`, сохраняя `ETag` и `Last-Modified`;
- HTML не получает долгий public-cache;
- HTML, CSS, JS, XML и достаточно большие JSON-ответы поддерживают gzip;
- PNG, WebP, JPEG, PDF, архивы, видео и web fonts повторно не сжимаются.

Внешние афиши из PostgreSQL не входят в файловый budget: приложение не скачивает,
не проксирует и не перекодирует их и не может гарантировать размер стороннего
файла. Оно обеспечивает размеры контейнера, lazy-loading карточек, безопасный
fallback и не выполняет backend GET/HEAD к `poster_url`.

## Повторная проверка

Сначала запустите локальное mock-приложение или обычный development server. Затем:

```powershell
python -m scripts.performance_audit audit --base-url http://127.0.0.1:8000 --json-output dist/performance-before.json --markdown-output dist/performance-before.md
python -m scripts.performance_audit structural-checks --report dist/performance-before.json
python -m scripts.performance_audit compare dist/performance-before.json dist/performance-after.json --fail-on-regression --markdown-output dist/performance-compare.md
```

Для production origin `--base-url` всегда задаётся явно. По умолчанию сторонние
resources блокируются; `--allow-third-party` включается только для осознанного
измерения внешних афиш. Скрипт не отправляет формы, не открывает Telegram CTA и не
передаёт отчёт внешним сервисам. Если Chromium отсутствует, он завершается с
командой установки браузера.

После deployment владелец вручную:

1. Проверяет mobile и desktop URL в PageSpeed Insights без утверждения результата
   до фактического прогона.
2. Добавляет `https://artflowfest.com` в Google Search Console и Яндекс Вебмастер.
3. Подтверждает владение выбранным способом, не сохраняя verification secrets в Git.
4. Отправляет `https://artflowfest.com/sitemap.xml` в обе панели.
5. Следит за индексацией, диагностикой и полевыми Core Web Vitals; у нового сайта
   полевые данные могут появиться не сразу.
