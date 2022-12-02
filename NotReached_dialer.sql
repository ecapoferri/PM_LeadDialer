SELECT
    l.id lead_id,
    co.val company,
    src.val lead_source,
    web.val website,
    CONCAT(e.name_first, " ", e.name_last) lead_owner,
    vert.val vertical,
    mkt.val market,
    ph.val phone,
    nm.val name_


FROM
    lead l

    LEFT JOIN (
        SELECT lead_id lid, value val
        FROM lead_data
        WHERE lead_field_id =54
    ) ph ON ph.lid = l.id

    LEFT JOIN (
        SELECT lead_id lid, value val
        FROM lead_data
        WHERE lead_field_id = 44
    ) co ON co.lid = l.id

    LEFT JOIN (
        SELECT lead_id lid, value val
        FROM lead_data
        WHERE lead_field_id = 40
    ) src ON src.lid = l.id

    LEFT JOIN (
        SELECT lead_id lid, value val
        FROM lead_data
        WHERE lead_field_id IN (64, 80)
            AND value IS NOT NULL
    ) web ON web.lid = l.id

    LEFT JOIN (
        SELECT lead_id, value val, MAX(modified) FROM (
                SELECT lead_id, value, modified
                FROM lead_data
                WHERE
                    lead_field_id = 35
                    OR
                    lead_field_id = 39
            UNION
                SELECT id lead_id, vertical value, modified
                FROM lead
        ) src_sub
        GROUP BY lead_id
    ) vert
        ON l.id = vert.lead_id

    LEFT JOIN (
        SELECT lead_id, value val, MAX(modified)
        FROM lead_data
        WHERE lead_field_id = 42
        GROUP BY lead_id
    ) mkt
        ON l.id = mkt.lead_id

    LEFT JOIN (
            SELECT lead_id, value val
            FROM lead_data
            WHERE lead_field_id = 76
        ) nm
        ON l.id = nm.lead_id


    LEFT JOIN member_employee e ON l.partner_rep = e.member_id

WHERE l.created >= '2022-06-01'
    AND src.val IN ('Google Paid Search', 'Bing', 'Chat', 'Phone In')
    AND l.status_id = 143
LIMIT 1000
;
