CREATE TABLE competitions (
    id INTEGER PRIMARY KEY,
    name TEXT,
    description TEXT,
    place TEXT,
    price TEXT,
    event_date DATE,
    application_deadline DATE,
    city TEXT,
    short_description TEXT,
    directions TEXT,
    poster_url TEXT,
    rules_url TEXT,
    is_published BOOLEAN NOT NULL,
    updated_at TIMESTAMP
);

CREATE TABLE faq (
    id INTEGER PRIMARY KEY,
    question TEXT,
    answer TEXT,
    create_at TIMESTAMP
);

INSERT INTO competitions (
    id,
    name,
    description,
    place,
    price,
    event_date,
    application_deadline,
    city,
    short_description,
    directions,
    poster_url,
    rules_url,
    is_published,
    updated_at
) VALUES
    (
        1,
        'Published competition',
        'Public description',
        'Test stage',
        '1000',
        DATE '2026-09-05',
        DATE '2026-09-01',
        'Almaty',
        'Public short description',
        'Vocal, Dance',
        'https://cdn.example.test/poster',
        'https://cdn.example.test/rules',
        TRUE,
        TIMESTAMP '2026-07-22 12:30:00'
    ),
    (
        2,
        'Unpublished competition',
        'Must not be returned',
        'Hidden stage',
        '2000',
        DATE '2026-10-05',
        DATE '2026-10-01',
        'Astana',
        'Hidden short description',
        'Theatre',
        NULL,
        NULL,
        FALSE,
        TIMESTAMP '2026-07-22 13:30:00'
    );

INSERT INTO faq (id, question, answer, create_at) VALUES
    (1, 'How to apply?', 'Use the competition Telegram link.', TIMESTAMP '2026-07-22 14:00:00');
