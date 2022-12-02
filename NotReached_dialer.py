# %% IMPORTS
import logging
import signal
import traceback
from datetime import datetime, timedelta
from io import StringIO
from os import environ
from pathlib import Path
from time import sleep
from urllib.parse import quote_plus, urlencode
import re

import pandas as pd
import pytz
import requests
from pandas import DataFrame as Df
from tqdm import tqdm

from db_engines import mms_db as db

from typing import Iterable


# %% input config ===================>
trailing_days = 185

# list of lead sources to filter for
results_filt: dict[str, list[str]] = {
    'lead_source': ['Google Paid Search']
}

lead_sql: str = re.sub(
    pattern=r'LIMIT \d*\n',
    repl='\n',
    string=re.sub(
        pattern=r'WHERE l\.created.*\n',
        repl="WHERE l.created >= '{min_date_str}'\n",
        string=Path('NotReached_dialer.sql').read_text()
    )
)


# Set to True to print debugging messages to stdout
we_are_debugging = True
# Set to True to avoid sending actual http requests, useful for debugging
# default should be False
testing_url_format = True
# == input config ===================<

# %% hard code config ==========================>
# for url formatting
quote_safe = '='  # character(s) to exclude in url encoding
# function to pass to url builder for regular encoding
quote_reg = lambda s: quote_plus(s, safe=quote_safe)
# ditto for website and emails as url args, straight string in double quotes
quote_quote = lambda s: f'"{s}"'

sql_ts_fmt = fmt_lg_ts = r'%Y-%m-%d %H:%M:%S'
tz_local = pytz.timezone('US/Central')

# first min datetime
now = datetime.now(tz=tz_local)
min_date_local = datetime(
        year=now.year,
        month=now.month,
        day=now.day,
        tzinfo=now.tzinfo
    ) - timedelta(days=trailing_days)
del now

min_date = min_date_local.astimezone(pytz.utc)
min_date_str: str = min_date.strftime(sql_ts_fmt)

# mininum time to allow for refreshes
refresh_min = 60

# logging config ==========================>
logger_top_name = 'NotReached_dialer'

log_file_name = Path(f"{__file__}-INFO.log")

ansilg = '\x1b[93m'
ansirst = '\x1b[0m'
fmt_lg_ts = r'%Y-%m-%d %H:%M:%S'
fmt_lg_prfx = '[%(asctime)s||%(name)s:%(module)s:%(funcName)s||%(levelname)s]'
fmt_lg_msg = ' >> %(message)s'

ansi_green = '\x1b[32m'
confirm_log_msg = \
    f"\n{ansi_green}\t{'[URL]': >6}{ansirst}"+\
    "\t{u}"+\
    f"\n{ansi_green}\t{'[Resp]': >6}{ansirst}"+\
    "\t{response}\n"

# <== logging config =====================<

# == HTTP REQUEST URL CONFIG ===========>
api_url = 'http://10.1.10.20/vicidial/non_agent_api.php'

# these args stay the same for each url
api_static_args: dict[str, str] = {
    'source': 'test',
    'user': '6666',
    'pass': 'RedLakeSky3501',
    'function': 'add_lead',
    'list_id': '104',
    'custom_fields': 'Y',
    'duplicate_check': 'DUPLIST30DAY',
}
# fields to update for each loop
variable_args: list[str] = [
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
dblquote_params: list[str] = ['Website']
quote_params: list[str] = [
    s for s in variable_args
    # exlude pre defined fields and dbl qoulte fields
    # static args
    if (not s in dblquote_params) & (s in variable_args)
]
#<== HTTP REQUEST URL CONFIG <=========<

#<== hard code config <=========================<



# %% fns
def logger_setup(debugging: bool=False, log_reset: bool=False) -> logging.Logger:

    if log_reset:
        log_file_name.write_text('', encoding='utf-8')

    fmt_lg_strm = f"{ansilg}{fmt_lg_prfx}{ansirst}{fmt_lg_msg}"
    fmt_lg_file = f"{fmt_lg_prfx}{fmt_lg_msg}"

    fmtr_strm: logging.Formatter
    fmtr_file: logging.Formatter
    fmtr_strm, fmtr_file = (logging.Formatter(fmt=f, datefmt=fmt_lg_ts) for f in (fmt_lg_strm, fmt_lg_file))

    hdlr_strm: logging.Handler = logging.StreamHandler()
    hdlr_file: logging.Handler = logging.FileHandler(log_file_name, encoding='utf-8')
    hdlr_file.setLevel(logging.INFO)

    output_lvl: int = logging.DEBUG if debugging else logging.INFO


    fmtrs = (
            (hdlr_strm, fmtr_strm),
            (hdlr_file, fmtr_file)
        )

    for hdlr, fmtr in fmtrs:
        hdlr.setFormatter(fmtr)
    del fmtrs

    logger_ = logging.getLogger(logger_top_name)

    for h in hdlr_strm, hdlr_file:
        logger_.addHandler(h)

    logger_.setLevel(output_lvl)

    return logger_


def query_url(
    api_url: str,
    arg_dict: dict,
    quote_params: Iterable[str],
    not_quote_params: Iterable[str],
    quote_norm,
    ampersand: bool=True,
    qmark: bool=True
) -> str:

    q: str = '?' if qmark else ''
    amp: str = '&' if ampersand else ''

    # f_args_str: str = urlencode(args)
    f_args_str: str = amp.join([
        f"{k}={quote_norm(v)}" if k in quote_params
        else f"{k}={v}"
        for k, v in arg_dict.items()
    ])
    return f"{api_url}{q}{f_args_str}"


def term_handler(signal_num, frame) -> None:
    lggr = logging.getLogger(logger_top_name)
    lggr.error(f"SIGTERM detected, BYE!")
    exit(0)


def url_builder(df_: Df, api_args_static: dict[str, str]) -> list[str]:
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
                not_quote_params=dblquote_params,
                quote_norm=lambda s: quote_plus(s, safe=quote_safe)
        ))

    return urls

def main():
    logger = logger_setup(debugging=we_are_debugging, log_reset=True)
    logger.info(f"Let's go!")
    logger.debug(f"Debugging...")
    if testing_url_format: logger.debug(f"***Testing URL construction only. No HTTP requests will be executed.***")

    logger.info(f"Starting at {min_date_str} UTC, ({min_date_local.strftime(sql_ts_fmt)} US/Central)")
    try:
        logger.debug(f"min datetime (utc time, tz naive, string): {min_date_str}")
        # plug minimum date into query
        query: str = lead_sql.format(min_date_str=min_date_str)
        # logger.debug(query)

        # extract from DB
        results: Df
        with db.connect() as conn:
            results = (
                pd.read_sql_query(query, conn)
            )
        logger.debug(f"results df: len, {len(results)}")
        log_buf = StringIO()
        results.info(buf=log_buf)
        logger.debug(f"Query results df, info:\n{log_buf.getvalue()}")

        if not len(results):
            logger.error(f"No Results within filter conditions")
        else:
            url_list = url_builder(results, api_static_args)

            if not len(url_list):
                logger.error(f"No urls processed!")
            else:
                # FIXME: make these async requests
                for u in url_list:
                    response = requests.Response()
                    try:
                        response = requests.Response() if testing_url_format else requests.get(u)

                        # format response text for logging messages, the html confirmation for 200s has a return in it
                        resp_log = f"resp: ({response.status_code}) >> {response.text}".replace('\n', '-|')

                        logger.info(
                            confirm_log_msg.format(
                                u=u,
                                response=resp_log if not testing_url_format
                                    else 'TESTING, NO REQUEST SENT'
                        ))

                    except Exception:
                        logger.error(
                            f"""ERROR ON:{confirm_log_msg.format(u=u, response=response)}

                            SEE TRACEBACK BELOW:

                            {traceback.format_exc()}"""
                            .replace('                            ', '')
                        )



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
