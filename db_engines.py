import traceback
from datetime import datetime
from os import environ
from pathlib import Path
from sqlite3 import Row
from typing import Any, Iterable, Literal

from dotenv import load_dotenv
from MySQLdb._exceptions import OperationalError as MySQL_OpErr
from pandas import DataFrame as Df
from pandas._typing import Dtype
from sqlalchemy import create_engine
from sqlalchemy.engine.base import Engine  # for type hints
from sqlalchemy.types import TypeEngine

load_dotenv()

#MMS/WO=MySQL config/s==============>
MMSWO_UN = environ['PRMDIA_SRVR_UN']
MMSWO_PW = environ['PRMDIA_SRVR_PW']
MMSWO_PORT = environ['PRMDIA_SRVR_DB_PORT']
MMSWO_HOST = environ['PRMDIA_SRVR_DB_HOST']
MMS_DB_NAME = environ['PRMDIA_SRVR_MMS_DB']
#<==MMS/WO=MySQL config/s=================<

#==Connection Engines========>
# connections to primedia dbs
MMS_CONN_STR = (
    f"mysql+mysqldb://{MMSWO_UN}:{MMSWO_PW}"
    + f"@{MMSWO_HOST}:{MMSWO_PORT}/{MMS_DB_NAME}"
)

MMS_DB = create_engine(MMS_CONN_STR)
#<==Connection Engines===========================<

def db_load(
            db: Engine,
            df: Df,
            tblnm: str,
            dtype: dict[Any, Dtype],
            presql: Iterable[str|None]|bool=False,
            xtrasql: Iterable[str|None]|bool=False,
            ifexists: Literal['fail', 'replace', 'append']='replace',
            index: bool=False
        ) -> None:
    """Shorthand function for an easy load to the local data sink db.
        No schema specified (will load to public on Postgres)

    Args:
        db (Engine): Database connection engine (sqlalchemy).
        df (Df): Dataframe to load.
        tblnm (str): Name of the table.
        dtype (dict[Any, Dtype]): Dictionary
            {<field>: <sqlalchemy type>}. Best to include all fields.
        presql (Iterable[str | None] | bool, optional): SQL queries to
            run before pd.Dataframe.to_sql. False types will be skipped.
            Defaults to False.
        xtrasql (Iterable[str | None] | bool, optional):SQL queries to
            run after pd.Dataframe.to_sql. False types will be skipped.
            Defaults to False.
        ifexists (Literal['fail', 'replace', 'append'], optional):
            Argument for pd.Dataframe.to_sql(if_exists).
            Defaults to 'replace'.
        index (bool, optional):
            Argument for pd.Dataframe.to_sql(index).
            Defaults to False. DO NOT USE.
    """
    with db.connect() as conn:
        if presql:
            [conn.execute(q) for q in presql]  # type: ignore
        df.to_sql(
            tblnm,
            conn,
            index=index,
            dtype=dtype,
            if_exists=ifexists,
        )
        if xtrasql:
            [conn.execute(q) for q in xtrasql]  # type: ignore
    return


def fs_tmstmp(path_: Path) -> str:
    """
    Args:
        path_ (pathlib.Path): Path to file from which we want the ts.

    Returns:
        str: TZ naive timestamp string with fmt: <yyyy-mm-dd hh:mm:ss>
    """
    tmstmp_fmt: str = r'%Y-%m-%d %H:%M:%S'

    tmstmp: str = (
        datetime
        .fromtimestamp(
            path_.stat()
            .st_mtime
        )
        .strftime(tmstmp_fmt))
    return tmstmp


def check_connection(db_: Engine) -> bool:
    """Checks that connection exists. Uses a basic query,
        not dependend on data in the DB.

    Args:
        db_ (Engine): sqlalchemy connection engine to check

    Raises:
        Exception: Try/Except excepts
            MySQLdb._exceptions.OperationalError (asliased as
            'MySQL_OpErr'). Raises basic exception to stop
            execution if that's the case.
    """
    with db_.connect() as conn:
        try:
            print(f"Checking {db_.engine} -->")
            rows = conn.execute(
                "SELECT 'Hello There' AS greeting;").all()
            rows_str: list[str] = [f"\t{r}" for r in rows]
            print(
                *rows_str,
                sep='\n',
                end='\n'
            )
            return True
        except MySQL_OpErr:
            print(traceback.format_exc())
            raise Exception(f"See above, bad connection...")
