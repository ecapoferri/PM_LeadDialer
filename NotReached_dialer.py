"""
Generalized module to send dmp/lead query results to vici dialer
"""
import logging
import traceback
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from urllib.parse import quote_plus
import re

import pandas as pd
import requests
from pandas import DataFrame as Df

from db_engines import mms_db as db

from typing import Iterable



def logger_setup(top_logger_name: str, debugging: bool=False, log_reset: bool=False) -> logging.Logger:
    ANSILG = '\x1b[93m'
    ANSIRST = '\x1b[0m'
    FMT_LG_TS = r'%Y-%m-%d %H:%M:%S'
    FMT_LG_PRFX = '[%(asctime)s||%(name)s:%(module)s:%(funcName)s||%(levelname)s]'
    FMT_LG_MSG = ' >> %(message)s'

    log_file = Path(f"{__file__}-INFO.log")

    if log_reset:
        log_file.write_text('', encoding='utf-8')

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
    hdlr_file: logging.Handler = logging.FileHandler(log_file, encoding='utf-8')
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


def query_url(
            api_url: str,
            arg_dict: dict,
            quote_params: Iterable[str],
            quote_safe: str,
            dblquote_params: Iterable[str],
            ampersand: bool=True,
            qmark: bool=True,
        ) -> str:

    quote_norm = lambda s: quote_plus(s, safe=quote_safe)
    dblquote = lambda s: f'"{s}"'

    q: str = '?' if qmark else ''
    amp: str = '&' if ampersand else ''

    args_strings: list[str] = []

    for k in quote_params:
        args_strings.append(f"{k}={quote_norm(arg_dict[k])}")

    for k in dblquote_params:
        args_strings.append(f"{k}={dblquote(arg_dict[k])}")

    the_rest = [
        k for k in arg_dict.keys()
        if k not in quote_params and k not in dblquote_params
    ]
    if the_rest:
        for k in the_rest:
            args_strings.append(f"{k}={arg_dict[k]}")



    # f_args_str: str = urlencode(args)
    f_args_str: str = amp.join([
        f"{k}={quote_norm(v)}" if k in quote_params
        else f"{k}={v}"
        for k, v in arg_dict.items()
    ])
    return f"{api_url}{q}{f_args_str}"


def url_builder(
            df_: Df, api_args_static: dict[str, str|int],
            api_url: str,
            quote_params: Iterable[str],
            dblquote_params: Iterable[str],
            quote_safe: str,
        ) -> list[str]:
    """spits out list of full url string

    Args:
        df_ (Df): _description_
        api_args_static (dict[str, str]): _description_

    Returns:
        list[str]: _description_
    """
    urls: list[str] = []

    for r in df_.itertuples():

        # some args are quote_plus, some are inside double quotes
        # this also elims the need for urllib.parse.urlencode
        args = {
            # no url encoding
            'phone_number': str(r.phone),
            'MMS_Lead_ID': str(r.lead_id),


            # regular quote_plus, '=' ok
            'Company_Name': str(r.company),
            'Lead_Source': str(r.lead_source),
            'Lead_Owner': str(r.lead_owner),
            'Vertical': str(r.vertical),
            'Media_Market': str(r.market),

            # bare string within ""
            # removes '-' lines from comments
            'Website': str(r.website),
            'first_name': str(r.name_)
        }



        # combine with recurring args
        api_args = api_args_static | args

        urls.append(
            query_url(
                api_url=api_url,
                arg_dict=api_args,
                quote_params=quote_params,
                dblquote_params=dblquote_params,
                quote_safe=quote_safe,
        ))

    return urls

def main():
    # Set to True to print debugging messages to stdout
    WE_ARE_DEBUGGING = True
    # Set to True to avoid sending actual http requests, useful for debugging
    # default should be False
    TESTING_URL_FORMAT = True
    # == input config ===================<

    LIST_ID = 104

    LOGGER_TOP_NAME = 'NotReached_dialer'

    SQL_SRC_FN = 'NotReached_dialer.sql'

    # list of lead sources to filter for

    lead_sql: str = re.sub(
        pattern=r'LIMIT \d*\n',
        repl='\n',
        string=re.sub(
            pattern=r'WHERE l\.created.*\n',
            repl="WHERE l.created >= '{min_date_str}'\n",
            string=Path(SQL_SRC_FN).read_text()
        )
    )


    # for url formatting
    QUOTE_SAFE = '='  # character(s) to exclude in url encoding

    # for logging messages
    ANSIRST = '\x1b[0m'
    ANSI_GREEN = '\x1b[32m'
    confirm_log_msg = \
        f"\n{ANSI_GREEN}\t{'[URL]': >6}{ANSIRST}"\
        + "\t{u}"\
        + f"\n{ANSI_GREEN}\t{'[Resp]': >6}{ANSIRST}"\
        + "\t{response}\n"

    API_URL = 'http://10.1.10.20/vicidial/non_agent_api.php'

    # these args stay the same for each url
    API_STATIC_ARGS: dict[str, str|int] = {
        'source': 'test',
        'user': '6666',
        'pass': 'RedLakeSky3501',
        'function': 'add_lead',
        'list_id': str(LIST_ID),
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
        'first_name'
    ]

    # fields that need a double quote string rather than spaces repalaced with '+'
    # 'Lead_Source' may need to be included here
    DBLQUOTE_PARAMS: list[str] = ['Website']
    quote_params: list[str] = [
        s for s in VARIABLE_ARGS
        # exlude pre defined fields and dbl qoulte fields
        # static args
        if (not s in DBLQUOTE_PARAMS)
    ]

    logger = logger_setup(top_logger_name=LOGGER_TOP_NAME, debugging=WE_ARE_DEBUGGING, log_reset=True)
    logger.info(f"Let's go!")
    logger.debug(f"Debugging...")
    if TESTING_URL_FORMAT: logger.debug(
        f"***Testing URL construction only. No HTTP requests will be executed.***")

    try:
        # plug minimum date into query
        # logger.debug(query)

        # extract from DB
        results: Df
        with db.connect() as conn:
            results = (
                pd.read_sql_query(lead_sql, conn)
            )
        logger.debug(f"results df: len, {len(results)}")
        log_buf = StringIO()
        results.info(buf=log_buf)
        logger.debug(f"Query results df, info:\n{log_buf.getvalue()}")

        if not len(results):
            logger.error(f"No Results within filter conditions")
        else:
            url_list = url_builder(
                df_=results,
                api_args_static=API_STATIC_ARGS,
                api_url=API_URL,
                quote_params=quote_params,
                dblquote_params=DBLQUOTE_PARAMS,
                quote_safe=QUOTE_SAFE
            )

            if not len(url_list):
                logger.error(f"No urls processed!")
            else:
                count_success = 0
                count_api_error = 0
                count_duplicates = 0
                count_bad_request = 0

                # FIXME: make these async requests
                for u in url_list:
                    response = requests.Response()
                    try:
                        response = requests.Response() if TESTING_URL_FORMAT else requests.get(u)

                        # format response text for logging messages, the html confirmation for 200s has a return in it

                        if response.status_code != 200:
                            logger.error(f"BAD REQUEST - resp: ({response.status_code}")
                            count_bad_request += 1

                        else:
                            resp_log = f"resp: ({response.status_code}) >> {response.text}".replace('\n', '-|')

                            log_msg = confirm_log_msg.format(
                                u=u,
                                response=resp_log if not TESTING_URL_FORMAT
                                else 'TESTING, NO REQUEST SENT'
                            )

                            if re.findall(r'SUCCESS:', response.text):
                                count_success += 1

                            elif re.findall(r'ERROR:', response.text):
                                count_api_error += 1

                                if re.findall(r'add_lead DUPLICATE PHONE NUMBER IN LIST', response.text):
                                    count_duplicates += 1

                            logger.debug(log_msg)


                    except Exception:
                        logger.error(
                            f"""ERROR ON:\n{confirm_log_msg.format(u=u, response=response)}

                            SEE TRACEBACK BELOW:

                            {traceback.format_exc()}"""
                            .replace('                            ', '')
                        )
            
                logger.info(f"Added to Vici Dialer: {count_success}\nNot Added: {count_api_error}/{count_duplicates} dups\nBad HTTP Requests: {count_bad_request}")



    except Exception:
        logger.error(traceback.format_exc())
        raise Exception("See above")
    finally:
        for h in logger.handlers:
            h.flush()
            h.close()
        return


# %% # GO!
if __name__ == "__main__":
    main()
