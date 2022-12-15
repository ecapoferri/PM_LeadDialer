# LeadDialer / ViciLoader

This is a proprietary/internal use script for Primedia Network. It automates exporting leads from the MMS Lead Developer database and loading those leads into the local ViciDialer server via a REST api type HTTP request.

## Installation

Prerequisites:

- Python 3.11+ (A dedicated virtual environment is recommended.)
- Jupyter Notebook support capable of selecting that env as interpreter
- A dedicated directory to drop output CSVs (see below) should already exist.

### Clone the repository

git clone ...FIXME:

### Install dependencies

```bash
[activate env]
$ cd .../PM_LeadDialer
$ pip install -r ./requirements.txt
```

### Dotenv

Create a `.env` in the repo directory with the following variables assigned as specified below:

- `PRMDIA_SRVR_PW`: DB server password
- `PRMDIA_SRVR_UN`: DB server username
- `PRMDIA_SRVR_DB_PORT`: DB server port
- `PRMDIA_SRVR_DB_HOST`: DB host server address (IPv4)
- `PRMDIA_SRVR_MMS_DB`: MMS database name
- `PRMDIA_VICI_BASESQL_PATH`: Path string to file with text for base SQL query. See above.
- `PRMDIA_VICI_LIST_DUMP_DIR_PATH`: Path to directory where backup CSVs will be written
- `PRMDIA_VICI_API_URL`: Base URL with endpoint for REST pi calls to load records to Vici-dialer.
- `PRMDIA_VICI_TOP_LOGGER`: Name for top level logger. Shared by modules to send messages to a common logger.

## Usage

Edit and run the notebook (`load_to_vici.ipynb`) as follows.

```python

The main module, `vici_loader.py` has the `load_to_vici` function. I found it best to def a function which calls `load_to_vici` to be threaded. Example:

def discovery(testing_url: bool):
    TABLE_LABEL = 'discovery_web_ad_leads-Lorraine'
    LIST_ID = 110
    SQL_WHERE = """
        AND l.status_id IN (159, 160)
        AND src.val in ('Bing', 'Chat', 'Google Paid Search', 'Phone In')
        AND CAST(CONVERT_TZ(l.created, 'UTC', 'US/Central') AS DATE)
            >= '2022-09-01'
        AND CAST(CONVERT_TZ(l.created, 'UTC', 'US/Central') AS DATE)
            < '2022-12-01'
    """
    # This is just to remove the extra whitespace, which was added to make the
    #   query more readable in code, so that it can be more readable if probing
    #   variables during debugging.
    sql_where = re.sub(r'\n {8}', '\n    ', SQL_WHERE)

    load_to_vici(
        list_id=LIST_ID,
        table_label=TABLE_LABEL,
        testing_url_format=testing_url,
        sql_where=sql_where,
        params_to_use=ALL_PARAMS,
    )
```

### `vici_loader.py`

Hard coded to run a query on the dmp database, load results to Vici, writes a backup CSV file which contains query results and logging information regarding the disposition of the HTTP request to the ViciDialer REST API. More documentation is available in the module comments.

### `vici_loader.load_to_vici` Parameters

- `table_label` : A general label for this instance being loaded to Vici. It will appear in log messages as well, which is very helpful when multithreading. It is also used for the name of the backup CSV.
- `list_id` : An integer of the list ID that is the intended destination for the records.
- `sql_where` : Limiting/filtering SQL WHERE clause to be added to the base SQL query (`dialer_base.sql`)
- `params_to_use` : This can be used to limit the fields sent to the Vici REST API. Any strings in the list must be accounted for in the `vici_loader.py` code (listed in `vici_loader.ALL_PARAMS: list[str]`).
- `testing_url_format` : If set to True, `vici_loader` will not make any HTTP requests. It is best to use this in conjunction with the logging level being set to `logging.DEBUG` to review URL construction.

## License

These scripts are not licensed - intended only for internal use at Primedia Network. Code is distributed only as an example of current processes. It does not contain any critical proprietary information.

Copyright 2022 Primedia Netowrk and Evan Capoferri
