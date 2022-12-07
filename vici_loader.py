"""
Generalized module to send dmp/lead query results to vici dialer

Main function will take input of
    - list_id: int - vici list id
    - sql_fragment: str - mainly WHERE clauses to be appended
        to the query in 'dialer_base.sql'
    - list_label: str - not sure if this is necessary,
        colloquial identifier for the list;
        this will also be helpful for diagnosing traceback
    TODO: - EXTRA CUSTOM FIELDS?

Main function should perform the following:
    TODO: load df based on the compiled query
    TODO: loop over the df and load entries to vici rest api
    TODO: provide logging feedback
    TODO: dump df of query results to a unique csv;
        This is because vici will reject results without a valid phone number.
"""
import logging
import traceback
from io import StringIO
from pathlib import Path
from urllib.parse import quote_plus
import re

import pandas as pd
import numpy as np

import requests
from pandas import DataFrame as Df

from db_engines import mms_db as DB

from os import environ as os_environ
from dotenv import load_dotenv
load_dotenv()

SQL_SRC_FN = os_environ['PRMDIA_VICI_BASESQL_PATH']
RE_SUB_PTN_LIMIT = r'\n*ORDER BY.*\n*LIMIT.*\n*;'
RE_SUB_REPL_LIMIT = '\n\n-- Added lines below\n{}\n;'

LOGGER_TOP_NAME = 'vici_loader'
#
lead_sql: str = re.sub(
    RE_SUB_PTN_LIMIT,
    RE_SUB_REPL_LIMIT,
    Path(SQL_SRC_FN).read_text())

# for url formatting
QUOTE_SAFE = '='  # character(s) to exclude in url encoding

# for logging messages
ANSIRST = '\x1b[0m'
ANSI_GREEN = '\x1b[32m'
confirm_log_msg = (
    f"\n{ANSI_GREEN}\t{'[URL]': >6}{ANSIRST}"
    + "\t{u}"
    + f"\n{ANSI_GREEN}\t{'[Resp]': >6}{ANSIRST}"
    + "\t{response}\n"
)

API_URL = 'http://10.1.10.20/vicidial/non_agent_api.php'

# these args stay the same for each url
API_STATIC_ARGS_: dict[str, str | int] = {
    'source': 'test',
    'user': '6666',
    'pass': 'RedLakeSky3501',
    'function': 'add_lead',
    'custom_fields': 'Y',
    'duplicate_check': 'DUPLIST30DAY',
}

# fields to update for each loop
VARIABLE_ARGS: list[str] = [
    'phone_number',
    'MMS_Lead_ID',
    'Company_Name',
    'Lead_Source',
    'Website',
    'Lead_Owner',
    'Vertical',
    'Media_Market',
    'first_name',
    'last_name'
]
# fields that need a double quote string rather than spaces repalaced with '+'
# 'Lead_Source' may need to be included here
DBLQUOTE_PARAMS: list[str] = [
    'Website',
    'email',
]


def logger_setup(
            top_logger_name: str,
            debugging: bool=False,
            log_reset: bool=True
        ) -> logging.Logger:
    ANSILG = '\x1b[93m'
    ANSIRST = '\x1b[0m'
    FMT_LG_TS = r'%Y-%m-%d %H:%M:%S'
    FMT_LG_PRFX = \
        '[%(asctime)s||%(name)s:%(module)s:%(funcName)s||%(levelname)s]'
    FMT_LG_MSG = ' >> %(message)s'

    mode = 'w' if log_reset else 'a'

    log_file = Path(f"{__file__}.log")

    fmt_lg_strm = f"{ANSILG}{FMT_LG_PRFX}{ANSIRST}{FMT_LG_MSG}"
    fmt_lg_file = f"{FMT_LG_PRFX}{FMT_LG_MSG}"

    fmtr_strm: logging.Formatter
    fmtr_file: logging.Formatter
    fmtr_strm, fmtr_file = (
        logging.Formatter(
            fmt=f,
            datefmt=FMT_LG_TS,
        )
        for f in (fmt_lg_strm, fmt_lg_file))

    hdlr_strm: logging.Handler = logging.StreamHandler()
    hdlr_file: logging.Handler = logging.FileHandler(
        log_file, encoding='utf-8', mode=mode)
    hdlr_file.setLevel(logging.INFO)

    output_lvl: int = logging.DEBUG if debugging else logging.INFO


    fmtrs = (
        (hdlr_strm, fmtr_strm),
        (hdlr_file, fmtr_file),
    )

    for hdlr, fmtr in fmtrs:
        hdlr.setFormatter(fmtr)
    del fmtrs

    logger_ = logging.getLogger(top_logger_name)

    for h in hdlr_strm, hdlr_file:
        logger_.addHandler(h)

    logger_.setLevel(output_lvl)

    return logger_


def extract_from_db(logger: logging.Logger, query: str) -> Df:
    df_: Df
    with DB.connect() as conn:
        df_ = pd.read_sql_query(query, conn)
    logger.debug(f"df_ df: len, {len(df_)}")
    log_buf = StringIO()
    df_.info(buf=log_buf)
    logger.debug(f"Query df_ df, info:\n{log_buf.getvalue()}")
    return df_


def api_param_arg_dict(row, static_args: dict) -> dict[str,str]:
    """Constructs a quick dictionary for this job. Used to pass to url
        encoding function

    Args:
        row (_type_): A NamedTuple from pandas.dataframe.itertuples
        static_args (dict): dictionary of args that don't need to be changed.

    Returns:
        dict[str,str]: Dict of parameters and args all converted to strings.
    """
    args = {
        # no url encoding
        'phone_number': str(row.phone),
        'MMS_Lead_ID': str(row.lead_id),

        # regular quote_plus, '=' ok
        'first_name': str(row.name),
        'last_name': str(row.name),
        'Company_Name': str(row.company),
        'Lead_Source': str(row.lead_source),
        'Lead_Owner': str(row.lead_owner),
        'Vertical': str(row.vertical),
        'Media_Market': str(row.market),

        # bare string within ""
        'Website': str(row.website),
        'email': str(row.email)
    }
    api_args = static_args | args
    return api_args


def url_builder_encoder(
            base_url: str, param_args: dict[str, str],
            q_mark: bool = True, ampersand: str = '&'
        ) -> str:
    q = '?' if q_mark else r''

    # Args for these params need to be the bare string within double quotes
    dblquote_params: list[str] = DBLQUOTE_PARAMS
    # Args for these params should be plus quoted
    encode_params: list[str] = [
        s for s in VARIABLE_ARGS
        # exlude pre defined fields and dbl qoulte fields
        # static args
        if (not s in dblquote_params)
    ]
    # The remaining should only be the static parameters.
    other_params = [
        param for param in param_args.keys()
        if
            param not in dblquote_params
            and
            param not in encode_params
    ]

    # Initializing a list to hold individual param=arg pair strings.
    params: list[str] = []
    for param in dblquote_params:
        params.append(f'{param}="{param_args[param]}"')

    for param in encode_params:
        enc = quote_plus(param_args[param], safe=QUOTE_SAFE)
        params.append(f'{param}={enc}')

    args = ampersand.join(params)
    return f"{base_url}{q}{args}"


def api_request(
            url: str,
            testing_url_format: bool = False,
        ) -> requests.Response:
    if testing_url_format:
        resp = requests.Response()
    else:
        resp = requests.get(url)

    return resp


def parse_response_text(
            response: requests.Response,
            counter_array: np.ndarray,
            url_string: str,
            testing_url: bool = False,
        ) -> tuple[str, np.ndarray]:
    API_SUCCESS = r'SUCCESS:'
    API_ERROR = r'ERROR:'
    API_DUP_ERROR = r'add_lead DUPLICATE PHONE NUMBER IN LIST'

    resp_log = f"resp: ({response.status_code}) >> {response.text}"\
        .replace('\n', '-|')

    msg = confirm_log_msg.format(
        u=url_string,
        response=resp_log if not testing_url
        else 'TESTING, NO REQUEST SENT'
        )


    if re.findall(API_SUCCESS, response.text):
        counter_array[0] += 1

    elif re.findall(API_ERROR, response.text):
        counter_array[1] += 1

        if re.findall(API_DUP_ERROR, response.text):
            counter_array[2] += 1


    return msg, counter_array


def load_to_vici(
            list_id: int, sql_where: str,
            table_label: str,
            we_are_debugging: bool = False,
            testing_url_format: bool = False,
        ):

    logger = logger_setup(
        top_logger_name=LOGGER_TOP_NAME,
        debugging=we_are_debugging,
    )
    logger.debug(f"Table Label: {table_label}\nWe are debugging, fyi...")
    if testing_url_format:
        logger.debug(
            f"***Testing URL construction only. No HTTP requests will be executed.***")

    # Add list ID to reusable args.
    api_static_args = API_STATIC_ARGS_ | {'list_id': str(list_id), }

    # Construct sql query
    sql_base_: str = Path(SQL_SRC_FN).read_text()
    # This is so we can leave a LIMIT clause in our SQL file for testing.
    sql_base = re.sub(RE_SUB_PTN_LIMIT, RE_SUB_REPL_LIMIT, sql_base_)
    # del sql_base_
    query = sql_base.format(sql_where)
    if we_are_debugging == 0:
        logger.debug(f"The query:\n")
        print(query)

    # extract df from DB
    results = extract_from_db(logger=logger, query=query)
    if not len(results):
        logger.error(f"No Results within filter conditions on this query")
        return

    # initialize the list to fill
    url_list: list[str] = []
    for r in results.itertuples():
        args = api_param_arg_dict(row=r, static_args=api_static_args)
        url = url_builder_encoder(base_url=API_URL, param_args=args)
        url_list.append(url)
    # logger.debug('\n'.join(url_list))

    if not len(url_list):
        logger.error(f"No urls processed from results?!")
        raise ValueError(f"No URLs processed")

    # Starting counters to summarize request responses.
    # count_success, count_api_error, count_duplicates, count_bad_request
    counters = np.array([0,0,0,0])

    for url in url_list:
        # Initialize the response variable to an empty requests.Response
        #   in case the request function fails.
        response: requests.Response = requests.Response()
        try:
            response: requests.Response = api_request(url)
        except Exception:
            logging.error(f"Error making request: {url}")

        # Format response text for logging messages.
        # The html confirmation has a return in it.
        if response.status_code != 200:
            logger.error(f"BAD REQUEST - resp: ({response.status_code}")
            counters[3] += 1
            # No need to parse the response text if not 200.
            continue

        log_msg, counters = parse_response_text(
            response=response, counter_array=counters, url_string=url,
            testing_url=testing_url_format)
        logger.debug(log_msg)


    count_success, count_api_error, count_duplicates, count_bad_request = counters

    logger.info(
        f"Added to Vici Dialer: {count_success}\n"
        + f"Not Added: {count_api_error}/{count_duplicates} dups\n"
        + f"Bad HTTP Requests: {count_bad_request}"
    )

    return


def test():
    # == input CONSTANTS ===================>
    # Set to True to print debugging messages to stdout
    WE_ARE_DEBUGGING = True
    # Set to True to avoid sending actual http requests, useful for debugging
    # default should be False
    TESTING_URL_FORMAT = True
    LIST_ID = 9999
    SQL_WHERE ="""--sql
        WHERE l.status_id in (142, 143, 45)
            AND CONVERT_TZ(l.created, 'UTC', 'US/Central') >= '2022-10-01'
            AND src.val IN ('Google Paid Search', 'Bing', 'Phone In', 'Chat')
        GROUP BY l.id
        ORDER BY l.modified DESC
    """.replace('--sql\n', '')
    sql_where = re.sub(r' {8}', '', SQL_WHERE)
    TABLE_LABEL = 'Test List'
    # == input CONSTANTS ===================>

    load_to_vici(
        list_id=LIST_ID,
        table_label=TABLE_LABEL,
        we_are_debugging=WE_ARE_DEBUGGING,
        testing_url_format=TESTING_URL_FORMAT,
        sql_where=sql_where,
    )

if __name__ == "__main__":
    test()