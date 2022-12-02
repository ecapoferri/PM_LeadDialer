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
# first min datetime
starting_line = '2022-11-14 17:00:00'
# time in seconds to check db
refresh_secs = 600
# list of lead sources to filter for
results_filt: dict[str, list[str]] = {
    'lead_source': ['Google Paid Search']
}

lead_sql: str = """--sql
    SELECT
        l.id lead_id,
        fn.val name_first,
        ln.val name_last,
        ph.val phone,
        em.val email,
        co.val company,
        src.val lead_source,
        web.val website,
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
    WHERE l.created >= '{last_str}'
    ;
""".replace('--sql', '')

# == input config ===================<

# %% hard code config ==========================>
# for url formatting
quote_safe = '='
quote_reg = lambda s: quote_plus(s, safe=quote_safe)  # regular encoding
quote_quote = lambda s: f'"{s}"'  # website and email encoding, straight string in double quotes

sql_ts_fmt = fmt_lg_ts = r'%Y-%m-%d %H:%M:%S'
tz_local = pytz.timezone('US/Central')

# where to start, maybe when restarting
first_last = (
    datetime.strptime(starting_line, sql_ts_fmt)
    .astimezone(tz_local)
    .astimezone(pytz.utc)
)
# set last rerfresh, this will be reset at each loop run
# setting an evn variable because this may switch from a while true / except to a chron job
last_str: str = first_last.strftime(sql_ts_fmt)
environ['pm_diallead_lastrefr'] = first_last.strftime(sql_ts_fmt)

# mininum time to allow for refreshes
refresh_min = 60

# set global time between refreshes
refresh = timedelta(seconds=float(
        refresh_secs if refresh_secs >= refresh_min else refresh_min
        )
    )

# logging config ==========================>
logger_top_name = 'lead_dialer_log'

logfile_err = Path(f"{__file__}-ERROR.log")
logfile_nfo = Path(f"{__file__}-INFO.log")

ansilg = '\x1b[93m'
ansirst = '\x1b[0m'
fmt_lg_ts = r'%Y-%m-%d %H:%M:%S'
fmt_lg_prfx = '[%(asctime)s||%(name)s:%(module)s:%(funcName)s||%(levelname)s]'
fmt_lg_msg = ' >> %(message)s'

we_are_debugging = True
testing_url_format = True
# <== logging config =====================<

# == HTTP REQUEST URL CONFIG ===========>
""" SAMPLE REQUEST URL:
        https://vici2201.theprimediagroup.com/vicidial/non_agent_api.php?source=test&user=6666&pass=RedLakeSky3501&function=add_lead&phone_number=6304189955&list_id=102&custom_fields=Y&duplicate_check=DUPLIST30DAY&first_name=Tim&last_name=Sels&MMS_Lead_ID=12345&email=“max@primedianetwork.com”&Lead_Source=google+paid+search&Company_Name=Test+Company&Website="www.google.com”&comments=interested+in+=+tv+advertising


    URL: https://vici2201.theprimediagroup.com/vicidial/non_agent_api.php?

    # STATIC ARGS:
        source=test
        user=6666
        pass=RedLakeSky3501
        function=add_lead
        phone_number=6304189955
        list_id=102
        custom_fields=Y
        duplicate_check=DUPLIST30DAY

    # PARAMS TO ARG:
        first_name=Tim  # QUOTE_PLUS STYLE
        last_name=Sels  # QUOTE_PLUS STYLE
        MMS_Lead_ID=12345  # INT-LIKE STRING, NO NEED TO QUOTE/ENCODE
        email=“max@primedianetwork.com”  # DOUBLE QUOTES STRING
        Lead_Source=google+paid+search  # QUOTE_PLUS STYLE
        Company_Name=Test+Company  # QUOTE_PLUS STYLE
        Website="www.google.com”  # DOUBLE QUOTES STRING
        comments=interested+in+=+tv+advertising  # QUOTE_PLUS STYLE
"""
api_url = 'https://vici2201.theprimediagroup.com/vicidial/non_agent_api.php'
param_args: dict[str, str] = {
    # STATIC ARGS:
    'source': 'test',
    'user': '6666',
    'pass': 'RedLakeSky3501',
    'function': 'add_lead',
    'list_id': '102',
    'custom_fields': 'Y',
    'duplicate_check': 'DUPLIST30DAY',
    # PARAMS TO ARG:
    'phone_number': '',
    'first_name': '',
    'last_name': '',
    'MMS_Lead_ID': '',
    'Company_Name': '',
    'email': '',
    'Lead_Source': '',
    'Website': '',
    'comments': ''
}
# fields to update for urlencode
fields_to_fill: list[str] = [
    'phone_number',
    'first_name',
    'last_name',
    'MMS_Lead_ID',
    'Company_Name',
    'email',
    'Lead_Source',
    'Website',
    'comments'
]
# fields that need a double quote string rather than spaces repalaced with '+'
dblquote_params: list[str] = ['email', 'Website']
quote_params: list[str] = [
    s for s in param_args.keys()
    # exlude pre defined fields and dbl qoulte fields
    if (not s in dblquote_params) & (s in fields_to_fill)
]
#<== HTTP REQUEST URL CONFIG <=========<

#<== hard code config <=========================<



# %% fns
def logger_setup(debugging: bool=False, log_reset: bool=False) -> logging.Logger:

    if log_reset:
        for p in logfile_err, logfile_nfo:
            p.write_text('', encoding='utf-8')

    fmt_lg_strm = f"{ansilg}{fmt_lg_prfx}{ansirst}{fmt_lg_msg}"
    fmt_lg_file = f"{fmt_lg_prfx}{fmt_lg_msg}"

    fmtr_strm: logging.Formatter
    fmtr_file: logging.Formatter
    fmtr_strm, fmtr_file = (logging.Formatter(fmt=f, datefmt=fmt_lg_ts) for f in (fmt_lg_strm, fmt_lg_file))

    hdlr_strm: logging.Handler = logging.StreamHandler()
    hdlr_file_dbg: logging.Handler = logging.FileHandler(logfile_nfo, encoding='utf-8')

    output_lvl: int = logging.DEBUG if debugging else logging.INFO

    lvlr = (
            (hdlr_strm, output_lvl),
            (hdlr_file_dbg, logging.INFO)
        )
    for hdlr, lvl in lvlr:
        hdlr.setLevel(lvl)
    del lvlr

    fmtrs = (
            (hdlr_strm, fmtr_strm),
            (hdlr_file_dbg, fmtr_file)
        )

    for hdlr, fmtr in fmtrs:
        hdlr.setFormatter(fmtr)
    del fmtrs

    logger_ = logging.getLogger(logger_top_name)

    for h in hdlr_strm, hdlr_file_dbg:
        logger_.addHandler(h)

    logger_.setLevel(logging.DEBUG)

    return logger_


def query_url(api_url: str, args_dict: dict, qmark: bool = True) -> str:
    """Assembles url with api parameters

    Args:
        api_url (str): api endpoint base url
            include reused parameters, set qmark to false to omit '?'
        args (dict): format pairs as <param>: <arg>
            use with your dynamic param/args
            use urllib.parse.quote to properly format strings as necessary
            before passing into this func
        qmark (bool, optional): Whether to include '?'. Defaults to True.

    Returns:
        str: full url encoded
    """
    q: str = '?' if qmark else ''
    # f_args_str: str = urlencode(args)
    f_args_str: str = '&'.join([
        f"{k}={v}" for k, v in args_dict.items()
    ])
    return f"{api_url}{q}{f_args_str}"


def query_url_A(
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


def url_constr_A(df_: Df, api_args: dict[str, str]) -> list[str]:
    urls: list[str] = []

    for r in df_.itertuples():

        # some args are quote_plus, some are inside double quotes
        # this also elims the need for urllib.parse.urlencode
        api_args.update({
            # no url encoding
            'MMS_Lead_ID': str(r.lead_id),
            'phone_number': str(r.phone), 

            # regular quote_plus, '=' ok
            'first_name': str(r.name_first),
            'last_name': str(r.name_last),
            'Company_Name': str(r.company),
            'Lead_Source': str(r.lead_source),
            'comments': re.sub(r'-+', '\n', str(r.comment)),

            # bare string within ""
            # removes '-' lines from comments
            'Website': str(r.website),
            'email': str(r.email),
        })

        urls.append(
            query_url_A(
                api_url=api_url,
                arg_dict=api_args,
                quote_params=quote_params,
                not_quote_params=dblquote_params,
                quote_norm=lambda s: quote_plus(s, safe=quote_safe)
        ))

    return urls



def main(last_str: str):
    signal.signal(signal.SIGTERM, term_handler)

    logger = logger_setup(debugging=we_are_debugging)
    logger.info(f"Let's go!")
    logger.debug(f"Debugging...")
    if testing_url_format: logger.debug(f"***Testing URL construction only. No HTTP requests will be executed.***")

    logger.info(f"Starting this run at (UTC) {datetime.utcnow().strftime(sql_ts_fmt)}")
    logger.info(f"Starting mininum datetime (UTC): {last_str}")

    try:
        while True:
            # clear any values that may be lagging from the previous itteration
            param_args.update({
                k: '' for k in fields_to_fill
            })

            # strings for sql query, converted to utc
            last_str = environ['pm_diallead_lastrefr']




            now = datetime.utcnow().astimezone(pytz.utc)

            query: str = lead_sql.format(last_str=last_str)
            logger.info(f"min datetime (utc time, tz naive, string): {last_str}")
            # logger.debug(query)

            results = Df()

            try:
                with db.connect() as conn:
                    results = (
                        pd.read_sql_query(query, conn)
                    )
                logger.debug(f"results df: len, {len(results)}")
                log_buf = StringIO()
                results.info(buf=log_buf)
                logger.debug(f"Query results df, info:\n{log_buf.getvalue()}")

            except Exception:
                logger.error(
                    f"There was an error querying querying DB:\n\n{traceback.format_exc()}")

            del query

            if not len(results):
                logger.info(f"No New Results from DB query.")
            else: 
                results = results.fillna(r'').astype('string')

                for col, lst in results_filt.items():
                    results = results.loc[results[col].isin(lst)]

                if not len(results):
                    logger.info(f"No Results within filter conditions")
                else:
                    url_list = url_constr_A(results, param_args)

                    if not len(url_list):
                        logger.error(f"No urls processed!")
                    else:
                        # FIXME: make these async requests
                        for u in url_list:
                            response = requests.Response()
                            log_msg = f"\n\t{'[URL]': >6}"+"\t{u}\n\t"+f"{'[Resp]': >6}\t"+"{response}"
                            try:
                                response = requests.Response() if testing_url_format else requests.get(u)
                                logger.info(
                                    log_msg.format(
                                        u=u,
                                        response=response if not testing_url_format else 'TESTING, NO REQUEST SENT'
                                ))
                            except Exception:
                                logger.error(
                                    f"""ERROR ON:{log_msg.format(u=u, response=response)}

                                    SEE TRACEBACK BELOW:

                                    {traceback.format_exc()}"""
                                    .replace('                            ', '')
                                )

                # set min timestamp for next run, only updated if run pulls results
                environ['pm_diallead_lastrefr'] = last_str = now.strftime(sql_ts_fmt)


    except KeyboardInterrupt:
        logger.info("Interrupt detected - BYE!")
    except Exception:
        logger.error(traceback.format_exc())
    finally:
        for h in logger.handlers:
            h.flush()
            h.close()
        return


# %% # GO!
if __name__ == "__main__":
    main(last_str=last_str)
