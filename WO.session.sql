SELECT COUNT(id), MIN(create_date)
FROM work_order_data
WHERE
    work_requested = 'Media RFP'
    AND `status` = 'Active'
;

SELECT
    SELECT id FROM work_order_data
    WHERE work_requested = 'Media RFP' AND `status` = 'Active'
