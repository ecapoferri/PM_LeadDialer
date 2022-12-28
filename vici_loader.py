import logging
from io import StringIO
from pathlib import Path
from urllib.parse import quote_plus
import re
from datetime import datetime, timedelta
import pandas as pd
from pandas import DataFrame as Df
import numpy as np
import traceback
import requests

from db_engines import MMS_DB as DB

from os import environ as os_environ
from dotenv import load_dotenv

from sqlalchemy.engine.base import Engine as SqlalchemyConnEngine

load_dotenv()
"""
Generalized module to send dmp/lead query results to vici dialer.

Main function will take input of
    - list_id: int - vici list id
    - sql_fragment: str - mainly WHERE clauses to be appended
        to the query in 'dialer_base.sql'
    - list_label: str - not sure if this is necessary,
        colloquial identifier for the list;
        this will also be helpful for diagnosing traceback
    - params to use: list - list of api url parameters to submit with
        arguments

Procedures:
    - extract df based on the compiled query
    - loop over the df and load entries to vici rest api
    - basic df cleanup
    - dump df of query results to a unique csv;
        This is because vici will reject results without a valid
        phone number.
    - provide logging feedback, verbose with debugging enabled.
"""
SQL_DATE_FMT = r'%Y-%m-%d'
SQL_SRC_FN = os_environ['PRMDIA_VICI_BASESQL_PATH']

LOGGER_TOP_NAME = os_environ['PRMDIA_VICI_TOP_LOGGER']

BACKUP_FILE_DIR = os_environ['PRMDIA_VICI_LIST_DUMP_DIR_PATH']

VICI_UN: str = os_environ['PRMDIA_VICI_UN']
VICI_PW: str = os_environ['PRMDIA_VICI_PW']

# For url formatting, the 'safe' argument for urllib.parse.quote or .quote_plus.
QUOTE_SAFE = '='

# Config and formatting for log messages.
ANSIRST = '\x1b[0m'
ANSI_GREEN = '\x1b[32m'
confirm_log_msg = (
    f"\n\t{'[URL]': >6}"
    + "\t{u}"
    + f"\n\t{'[Resp]': >6}"
    + "\t{response}\n"
)
# # This is an alternate version for stdout/stderr ouput, colorized.
# confirm_log_msg = (
#     f"\n{ANSI_GREEN}\t{'[URL]': >6}{ANSIRST}"
#     + "\t{u}"
#     + f"\n{ANSI_GREEN}\t{'[Resp]': >6}{ANSIRST}"
#     + "\t{response}\n"
# )

# Constants for API requests.
API_URL = os_environ['PRMDIA_VICI_API_URL']
# These args stay the same for each url
API_STATIC_ARGS_: dict[str, str | int] = {
    'source': quote_plus(__name__),
    'user': VICI_UN,
    'pass': VICI_PW,
    'function': 'add_lead',
    'custom_fields': 'Y',
    'duplicate_check': 'DUPLIST30DAY',
}
# Parameters that must be included in the http request url:
STATIC_REQUIRED_ARGS: list[str] = [
    'list_id',
    'source',
]
VARIABLE_REQUIRED_ARGS: list[str] = [
    'phone_number',
]
# fields that need a double quote string rather rather than
#   plus style url quoted
DBLQUOTE_PARAMS: list[str] = [
    'Website',
    'email',
]
# This can be used to map query results fields to pair as arguments
#   with their respective api url parameters.
PARAM_ARG_FIELDS_MAP: dict[str, str] = {
    'phone_number': 'phone',
    'first_name': 'name_first',
    'last_name': 'name_last',
    'comments': 'comments',
    'address1': 'company_address',
    'address2': 'company_suite',
    'city': 'company_city',
    'state': 'company_state',
    'postal_code': 'company_zip',
    'MMS_Lead_ID': 'lead_id',
    'Vertical': 'vertical',
    'Media_Market': 'market',
    'Lead_Source': 'lead_source',
    'Lead_Owner': 'lead_owner',
    'Company_Name': 'company',
    'email': 'email',
    'Website': 'website',
}
# Two different addresses are queried. One is used to .fillna the other.
COMP_ADDRESS_FIELDS = [
    'company_address',
    'company_city',
    'company_state',
    'company_zip',
]
BUIS_ADDRESS_FIELDS = [
    'business_address',
    'business_city',
    'business_state',
    'business_zip',
]
# Maximum length of comments field for the API URL args.
VICI_MAX_LEN_COMMENTS = 255
# List of all parameters currently available to use in this module.
#   This can be easily imported from this module for use in the notebook.
ALL_PARAMS: list[str] = [
    'phone_number',
    'first_name',
    'last_name',
    'comments',
    'address1',
    'address2',
    'city',
    'state',
    'postal_code',
    'MMS_Lead_ID',
    'Company_Name',
    'Lead_Source',
    'Website',
    'Lead_Owner',
    'Vertical',
    'Media_Market',
]


LOGGER = logging.getLogger(LOGGER_TOP_NAME)


def parse_sql_query(where_date: str, sql_where: str) -> str:
    RE_SUB_PTN_LIMIT =\
        r'\n\s*AND l.status_id NOT IN \(100, 96, 144\)\n*ORDER BY.*\n*LIMIT.*\n*;'
    RE_SUB_REPL_LIMIT =\
        f"\n    AND l.status_id NOT IN (100, 96, 144)\n"\
        + f"    AND l.created >= '{where_date}'\n-- Added lines below\n"\
        + f"{sql_where}\n;"\
            if len(where_date)\
            else\
        f"\n    AND l.status_id NOT IN (100, 96, 144)\n-- Added lines below\n{sql_where}\n;"

    # Construct sql query
    sql_base: str = Path(SQL_SRC_FN).read_text()
    # This is so we can leave a LIMIT clause in our SQL file for testing.
    # sql_base = re.sub(RE_SUB_PTN_LIMIT, RE_SUB_REPL_LIMIT, sql_base)
    # query = sql_base.format(where_date=where_date, where_else=sql_where)
    query = re.sub(RE_SUB_PTN_LIMIT, RE_SUB_REPL_LIMIT, sql_base)
    LOGGER.debug(query)

    return query


def extract_from_db(
        query: str, db: SqlalchemyConnEngine, table_label: str) -> Df:
    """
    Args:
        query (str): Completed SQL query to get desired info from the
            lead schema from the dmp db (`lead` and `lead_data` with
            some joins to `status` and `member_employee` etc.). Should
            use the predefined dialer_base.sql query with added
            WHERE statements.
        db (SqlalchemyConnEngine): Sqlalchemy DB engine for the
            dmp database.
        table_label (str): Used for logging feedback.
            Helpful to distinguish log messages while multithreading
            multiple instances of the main function in this module.
        last_run_date (str): Date (UTC) to use a minimum for the query.

    Returns: pandas.Dataframe with desired results
    """
    try:
        df_: Df
        with DB.connect() as conn:
            df_ = pd.read_sql_query(query, conn)
        LOGGER.info(f"{table_label}: df_ df: len, {len(df_)}")
        log_buf = StringIO()
        df_.info(buf=log_buf)
        LOGGER.debug(f"{table_label}: Query df_ df, info:\n{log_buf.getvalue()}")
        return df_
    except Exception:
        LOGGER.error(f"Error on query to DSB{traceback.format_exc()}")
        raise ValueError(f"\nError on query to MMS DB. See traceback above")


def process_df(df_: Df) -> Df:
    """Hard coded cleanup of the resulting Dataframe.

    Args: df_ (Df): Dataframe to clean up, must be a query result
        generated by this module's extract_from_db function.
    """
    df_c = df_.copy()
    out_cols = [c for c in df_.columns if c not in BUIS_ADDRESS_FIELDS]

    # Fill in missing 'company address';
    #   essentially unify into one set of fields.
    # This truth series will limit the records being replaced to
    #   only where Company Address is completely blank
    address_truth = (df_c[COMP_ADDRESS_FIELDS]
                    .isna().all(axis=1))
    address_zipper = zip(COMP_ADDRESS_FIELDS, BUIS_ADDRESS_FIELDS)
    for comp, buis in address_zipper:
        df_c.loc[address_truth, comp] =(
            df_c.loc[address_truth, comp]
            .fillna(df_c.loc[address_truth, buis])
        )

    # Pretty up name fields.
    for c in 'name_first', 'name_last':
        df_c[c] = df_c[c].str.title()

    # Replace repeating dashes found sometimes.
    df_c['comments'] =\
        df_c['comments'].str.replace(pat=r'-+', repl='-', regex=True)
    # Trim comments field down to max length for vici.
    df_c['comments'] = df_c['comments'].str.slice(stop=VICI_MAX_LEN_COMMENTS)

    return df_c[out_cols]


def api_param_arg_dict(
            row: tuple,
            static_args: dict,
            param_list: list[str]
        ) -> dict[str,str]:
    """Constructs a quick dictionary for this job. Used to pass to url
        encoding function

    Args:
        row (_type_): A NamedTuple from pandas.dataframe.itertuples
        static_args (dict): dictionary of args that don't need to be
        changed.

    Returns:
        dict[str,str]: Dict of params and args all converted to strings.
    """
    if not len(param_list):
        raise ValueError(
            f"There are no elements in the list passed: 'param_list'")

    # Add required paramters to the list
    param_list += (
        VARIABLE_REQUIRED_ARGS
    )
    # remove any required args to prevent duplicate entries
    param_list = list(set(param_list))

    args = {}
    # Extracts each value from the row NamedTuple
    for p in param_list:
        args.update({p: str(getattr(row, PARAM_ARG_FIELDS_MAP[p]))})
    api_args = static_args | args
    return api_args


def url_builder_encoder(
            base_url: str, param_args: dict[str, str],
            q_mark: bool = True, ampersand: str = '&'
        ) -> str:
    """Constructs URL to make HTTP GET request to make the API call
        later in this module.

    Args:
        base_url (str): The base url including endpoint.
        param_args (dict[str, str]): Dict of parameters and arguments,
            constructed by api_param_arg_dict in this script/module.
        q_mark (bool, optional): Whether to use '?' between endpoint
            and arguments. Defaults to True.
        ampersand (str, optional): Character to use between
            parameter/argument pairs. Defaults to '&', obviously.

    Returns:
        str: Complete URL ready for HTTP GET request.
    """
    q = '?' if q_mark else r''

    params_to_use: list[str] = list(param_args.keys())

    # Args for these params need to be the bare string within double quotes
    dblquote_params: list[str] = DBLQUOTE_PARAMS
    # Args for these params should be plus quoted
    encode_params: list[str] = [
        s for s in params_to_use
        # exlude pre defined fields and dbl qoulte fields
        #   static args
        if (not s in dblquote_params)
    ]
    # The remaining should only be the static parameters.
    other_params = [
        param for param in params_to_use
        if
            param not in dblquote_params
            and
            param not in encode_params
    ]

    # Initializing a list to hold individual param=arg pair strings.
    params: list[str] = []

    for param in other_params:
        if param not in params_to_use: continue
        params.append(f'{param}={param_args[param]}')

    for param in encode_params:
        if param not in params_to_use: continue
        # Skip if the arg value is None. phone_number is required
        if param_args[param] == 'None' and param != 'phone_number': continue
        enc = quote_plus(param_args[param], safe=QUOTE_SAFE)
        params.append(f'{param}={enc}')

    for param in dblquote_params:
        if param not in params_to_use: continue
        # Skip if the arg value is None.
        if param_args[param] == 'None': continue
        params.append(f'{param}="{param_args[param]}"')

    args = ampersand.join(params)
    return f"{base_url}{q}{args}"


def parse_response_text(
            response: requests.Response,
            counter_array: np.ndarray,
            url_string: str,
            testing_url: bool,
        ) -> tuple[str, str, np.ndarray]:
    """Parses HTTP response (response code and text content) and
        produces log messages for feedback.

    Args:
        response (requests.Response): Response object resulting from
            HTTP request elsewhere in this module.
        counter_array (np.ndarray): Array of ints only,
            must be of shape (4,).
        url_string (str): The string of the URL used for the
            HTTP Request. Used to add to the compiled log messages.
        testing_url (bool, optional): Whether this module is running
            as a test (not sending HTTP requests). Defaults to False.

    Returns:
        tuple[str, str, np.ndarray]:
            tuple(
                msg: Fully compiled log message.,
                resp_log: Inner message, just a parsing of HTTP
                    response text and code. Included in msg.,
                counter_array: updated counter returned to
                    main function.,
            )
    """
    api_success = r'SUCCESS:'
    api_error = r'ERROR:'
    api_dup_error = r'add_lead DUPLICATE PHONE NUMBER IN LIST'

    if not testing_url:
        resp_log = f"resp: ({response.status_code}) >> {response.text}"\
            .replace('\n', '-|')
    else: resp_log = 'TESTING, NO REQUEST SENT'

    if re.findall(api_success, response.text):
        counter_array[0] += 1

    elif re.findall(api_error, response.text):
        counter_array[1] += 1

        if re.findall(api_dup_error, response.text):
            counter_array[2] += 1

    msg = confirm_log_msg.format(
        u=url_string,
        response=resp_log 
    )

    return msg, resp_log, counter_array


def load_to_vici(
            list_id: int, sql_where: str,
            table_label: str,
            params_to_use: list[str],
            where_date: str = '',
            testing_url_format: bool = False,
        ):
    """
    Generalized module to extract dmp/lead query results
        and load to vici dialer

    Args:
        list_id (int): Vici list id
        sql_where (str): WHERE clauses to be added to base SQL query.
        where_date (str): Minium date to be inserted into WHERE clauses.
        table_label (str): General Identifier for the specific list
            being queried from the lead DB.
        testing_url_format (bool, optional): To disable (if True)
            actually sending http requests.
            Useful for reviewing or debugging URL construction.
            Defaults to False.

    Raises:
        ValueError: Raised if no results load from the query
            or there is a problem constructing urls.
    """
    LOGGER.info(f"{table_label}: Running...")
    LOGGER.debug(f"Table Label: {table_label}\n\tWe are debugging, fyi...")
    if testing_url_format:
        LOGGER.warning(f"***Testing URL construction only. "
            + f"No HTTP requests will be executed.***")

    # Add list ID to reusable args.
    api_static_args = API_STATIC_ARGS_ | {'list_id': str(list_id), }

    query = parse_sql_query(where_date=where_date, sql_where=sql_where)

    # Extract df from DB and do some cleanup.
    results = (
        extract_from_db(query=query, db=DB, table_label=table_label)
        .pipe(process_df)
    )
    if not len(results):
        LOGGER.error(
            f"{table_label}: No Results within filter conditions on this query")
        raise ValueError(f"No Results within filter conditions on this query")

    LOGGER.info(f"{len(results.index)} loaded from DB for {table_label}")

    # Build list of URLs based on df values.
    # initialize the list to fill
    url_list: list[tuple[int, str]] = []
    for r in results.itertuples():
        idx: int = r.Index
        args = api_param_arg_dict(
            row=r, static_args=api_static_args,
            param_list=params_to_use
        )
        url = url_builder_encoder(base_url=API_URL, param_args=args)
        url_list.append((idx, url))

    if not len(url_list):
        LOGGER.error(f"{table_label}: No urls processed from results?!")
        raise ValueError(f"{table_label}: No URLs processed")

    # Starting counters to summarize request responses.
    #   count_success, count_api_error, count_duplicates, count_bad_request
    counters = np.array([0,0,0,0])
    # Start a list of dispos to join back to the df for backup
    dispositions: dict[int, tuple[str]] = {}
    for idx, url in url_list:
        # Initialize the response variable to an empty requests.Response
        #   in case the request function fails.
        response: requests.Response = requests.Response()

        if not testing_url_format:
            try:
                response = requests.get(url)
                #   The html confirmation has a return in it.
                if response.status_code != 200:
                    LOGGER.error(f"{table_label}: BAD REQUEST - resp: "
                        + f"({response.status_code}")
                    counters[3] += 1
                    # No need to parse the response text if not 200.
                    continue

            except Exception:
                logging.error(f"{table_label}: Error making request: {url}")
                continue

        # Format response text for logging messages.
        log_msg, resp_log, counters = parse_response_text(
            response=response, counter_array=counters, url_string=url,
            testing_url=testing_url_format)
        LOGGER.info(f"{table_label}:{log_msg}")

        dispositions.update({idx: (resp_log,)})

    count_success, count_api_error, count_duplicates, count_bad_request=\
        counters

    LOGGER.info(
        '\n'
        + f"{table_label}:\n"
        + f"\tAdded to Vici Dialer: {count_success}\n"
        + f"\tNot Added: {count_api_error}/{count_duplicates} dups\n"
        + f"\tBad HTTP Requests: {count_bad_request}\n"
    )

    # Output to backup CSV.
    # Need to remove newlines from the comments field
    results['comments'] = results['comments'].str.replace('\n', '||')
    # Join dispos to csv for logging review.
    out_path = Path(BACKUP_FILE_DIR) / f"{table_label}.csv"
    results = results.join(Df.from_dict(
            dispositions, orient='index', columns=['vici_log']
        )['vici_log'])
    results.to_csv(
        path_or_buf=out_path,
        index=False, encoding='utf-8'
    )
    LOGGER.info(f"{table_label}: Wrote {out_path.__str__()}")

    return


def test():
    # == input CONSTANTS ===================>
    LIST_ID = 9999
    SQL_WHERE ="""--sql
            AND l.status_id in (142, 143, 45)
            AND CONVERT_TZ(l.created, 'UTC', 'US/Central') >= '2022-10-01'
            AND src.val IN ('Google Paid Search', 'Bing', 'Phone In', 'Chat')
        GROUP BY l.id
        ORDER BY l.modified DESC
    """.replace('--sql\n', '')
    sql_where = re.sub(r' {8}', '', SQL_WHERE)
    TABLE_LABEL = 'test_list'
    TESTING_URL_FORMAT = True


    # fields to update for each loop
    ARGS_TO_USE: list[str] = [
        'phone_number',
        'first_name',
        'last_name',
        'comments',
        'address1',
        'address2',
        'city',
        'state',
        'postal_code',
        'email',
        'MMS_Lead_ID',
        'Company_Name',
        'Lead_Source',
        'Website',
        'Lead_Owner',
        'Vertical',
        'Media_Market',
    ]
    # == input CONSTANTS ===================>
    LOGGER.warning(f"*Running test*")
    load_to_vici(
        list_id=LIST_ID,
        table_label=TABLE_LABEL,
        testing_url_format=TESTING_URL_FORMAT,
        sql_where=sql_where,
        where_date=(
            datetime.utcnow().date() - timedelta(days=1)).strftime(r'%Y-%m-%d'),
        params_to_use=ARGS_TO_USE
    )


if __name__ == "__main__":
    LOGGER.setLevel(logging.DEBUG)
    test()