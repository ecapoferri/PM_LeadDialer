# %%

import numpy as np
import pandas as pd
from pandas import Series as Ser, DataFrame as Df


s104 = """MMS_Lead_ID
Lead ID
AREA
Lead_Source
Lead Source
TEXT
Vertical
Vertical
AREA
Media_Market
Media Market
AREA
Company_Name
Company Name
AREA
Website
Website
TEXT
Lead_Owner
Lead Owner
AREA""".split('\n')

s105_cols = ['param', 'descr',
    'type\nTEXT=unencoded, in double quotes,\nAREA=regular url encoding'
]

"""TOTALS: 7        381"""

a104 = np.reshape(s104,(-1,3))


s103 = """1 - 1
MMS_Lead_ID
Lead ID
AREA
45
1 - 1
Vertical
Vertical
AREA
45
2 - 1
Lead_Source
Lead Source
TEXT
78
3 - 1
Media_Market
Media Market
AREA
45
4 - 1
Company_Name
Company Name
AREA
45
4 - 1
Website
Website
TEXT
78""".split('\n')

a103 = np.reshape(s103,(-1,5))
a103_cols = [0, 'param', 'descr',
    'type\nTEXT=unencoded, in double quotes,\nAREA=regular url encoding', 1]

# %%
# df = Df(a, columns=s105_cols)
