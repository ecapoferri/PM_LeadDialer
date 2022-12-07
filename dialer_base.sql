SELECT
    l.id lead_id,
    l.partner_rep lead_owner_id,
    CONCAT(e.name_first, ' ', e.name_last) lead_owner,
    l.status_id status_id,
    `status`.`name` "status",

    src.val lead_source,

    mkt.val market,
    vert.val vertical,

    co.val company,
    web.val website,

    nm.val "name",
    ph.val phone,
    em.val email,

    co_add1.val company_address,
    co_add2.val company_suite,
    co_city.val company_city,
    co_st.val company_state,
    co_z.val company_zip,

    b_add1.val business_address,
    b_city.val business_city,
    b_st.val business_state,
    b_z.val business_zip

FROM
    lead l

    LEFT JOIN ( -- phase2 phone contact, "phone"
        SELECT lead_id lid, value val
        FROM lead_data
        WHERE lead_field_id = 54
    ) ph ON ph.lid = l.id

    LEFT JOIN ( -- company name, "company"
        SELECT lead_id lid, value val
        FROM lead_data
        WHERE lead_field_id = 44
    ) co ON co.lid = l.id

    LEFT JOIN ( -- "lead_source"
        SELECT lead_id lid, value val
        FROM lead_data
        WHERE lead_field_id = 40
    ) src ON src.lid = l.id

    LEFT JOIN ( -- "website"
        SELECT lead_id lid, value val
        FROM lead_data
        WHERE lead_field_id IN (64, 80)
            AND value IS NOT NULL
    ) web ON web.lid = l.id

    LEFT JOIN ( -- "vertical"
        SELECT lead_id lid, value val
        FROM lead_data
        WHERE lead_field_id = 39
    ) vert
        ON l.id = vert.lid

    LEFT JOIN ( -- media_market, 'Market of Media' - "market"
        SELECT lead_id, value val, MAX(modified)
        FROM lead_data
        WHERE lead_field_id = 42
        GROUP BY lead_id
    ) mkt
        ON l.id = mkt.lead_id

    LEFT JOIN ( -- 'business_contact2', 'Contact Name #2' - "name"
            SELECT lead_id, value val
            FROM lead_data
            WHERE lead_field_id = 76
    ) nm
    ON l.id = nm.lead_id

    LEFT JOIN ( -- "email"
            SELECT lead_id, value val
            FROM lead_data
        WHERE lead_field_id = 57
    ) em
    ON l.id = em.lead_id

    LEFT JOIN ( -- Company Address 1
        SELECT
            value val,
            lead_id lid
        FROM lead_data
        WHERE lead_field_id IN (59)
    ) co_add1
    ON co_add1.lid = l.id

    LEFT JOIN ( -- Company Address 2
        SELECT
            value val,
            lead_id lid
        FROM lead_data
        WHERE lead_field_id IN (60)
    ) co_add2
    ON co_add2.lid = l.id

    LEFT JOIN ( -- Company Address City
        SELECT
            value val,
            lead_id lid
        FROM lead_data
        WHERE lead_field_id IN (61)
    ) co_city
    ON co_city.lid = l.id

    LEFT JOIN ( -- Company Address State
        SELECT
            value val,
            lead_id lid
        FROM lead_data
        WHERE lead_field_id IN (62)
    ) co_st
    ON co_st.lid = l.id

    LEFT JOIN ( -- Company Address Zip
        SELECT
            value val,
            lead_id lid
        FROM lead_data
        WHERE lead_field_id IN (63)
    ) co_z
    ON co_z.lid= l.id

    LEFT JOIN ( -- Business Address 1
        SELECT
            value val,
            lead_id lid
        FROM lead_data
        WHERE lead_field_id IN (68)
    ) b_add1
    ON b_add1.lid = l.id

    LEFT JOIN ( -- Business Address City
        SELECT
            value val,
            lead_id lid
        FROM lead_data
        WHERE lead_field_id IN (70)
    ) b_city
    ON b_city.lid = l.id

    LEFT JOIN ( -- Business Address State
        SELECT
            value val,
            lead_id lid
        FROM lead_data
        WHERE lead_field_id IN (71)
    ) b_st
    ON b_st.lid = l.id

    LEFT JOIN ( -- Business Address Zip
        SELECT
            value val,
            lead_id lid
        FROM lead_data
        WHERE lead_field_id IN (72)
    ) b_z
    ON b_z.lid = l.id
    -- "lead_owner"
    LEFT JOIN member_employee e ON l.partner_rep = e.member_id

    LEFT JOIN `status` ON l.status_id = `status`.id

ORDER BY l.created DESC
LIMIT 1000
;
