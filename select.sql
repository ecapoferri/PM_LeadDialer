SELECT
    l.id lead_id,
    fn.val name_first,
    ln.val name_last,
    ph.val phone,
    em.val email,
    co.val company,
    src.val lead_source,
    web.val website,
    cmt.val website,
    cmt.val comment

FROM
    lead l
    LEFT JOIN (
        SELECT lead_id lid, value val
        FROM lead_data
        WHERE lead_field_id  = 51
    ) fn ON fn.lid = l.id
    LEFT JOIN (
        SELECT lead_id lid, value val
        FROM lead_data
        WHERE lead_field_id = 52
    ) ln ON ln.lid = l.id
    LEFT JOIN (
        SELECT lead_id lid, value val
        FROM lead_data
        WHERE lead_field_id =54
    ) ph ON ph.lid = l.id
    LEFT JOIN (
        SELECT lead_id lid, value val
        FROM lead_data
        WHERE lead_field_id = 57
    ) em ON em.lid = l.id
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
        SELECT d.lead_id lid, d.value val
        FROM lead_data d
            LEFT JOIN lead_field f
            ON f.id = d.lead_field_id
        WHERE lead_field_id = 50
    ) cmt ON cmt.lid = l.id
    -- LEFT JOIN (
    --     SELECT d.lead_id lid, d.value val, f.name fldn, f.label fldlab, d.lead_field_id fid
    --     FROM lead_data d
    --         LEFT JOIN lead_field f
    --         ON f.id = d.lead_field_id
    --     WHERE lead_field_id IN (
    --         SELECT id FROM lead_field
    --         WHERE name REGEXP '.*[Cc]omment.*'
    --         OR label REGEXP '.*[Cc]omment.*'
    --     )
    -- ) cmt ON cmt.lid = l.id

WHERE l.created >= '2022-11-14 18:24:47'

;
