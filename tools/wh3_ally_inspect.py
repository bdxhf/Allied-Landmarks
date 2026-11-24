from pathlib import Path
import struct,re,lzma,zstandard,ctypes,os,sys
def game_data_directory():
    game_path = os.environ.get('WH3_GAME_DIR')
    if game_path:
        return Path(game_path).expanduser().resolve() / 'data'
    for parent in Path(__file__).resolve().parents:
        candidate = parent / 'common' / 'Total War WARHAMMER III' / 'data'
        if (candidate / 'db.pack').is_file():
            return candidate
    raise SystemExit('Set WH3_GAME_DIR to the Total War WARHAMMER III installation directory.')


D = game_data_directory()
schema_default = Path(os.environ['APPDATA']) / 'FrodoWazEre/rpfm/config/schemas/schema_wh3.ron'
S = Path(os.environ.get('WH3_SCHEMA_PATH', schema_default)).read_text('utf8')


def index(file):
 f=file.open('rb'); magic,fl,_,deps,n,size,_=struct.unpack('<4s6I',f.read(28)); f.seek(deps,1); idx=f.read(size); off=f.tell(); p=0; res={}
 for i in range(n):
  length,compressed=struct.unpack_from('<IB',idx,p); end=idx.index(0,p+5); name=idx[p+5:end].decode(); res[name]=(off,length,compressed); p=end+1; off+=length
 return f,res
def extract(pack,key):
 f,idx=pack; o,n,c=idx[key]; f.seek(o); b=f.read(n)
 if not c:return b
 if b[4:8]==bytes.fromhex('04224d18'):
  import lz4.frame
  payload=lz4.frame.decompress(b[4:])
  if len(payload)!=int.from_bytes(b[:4],'little'):raise ValueError('Invalid LZ4 size: '+key)
  return payload
 if b[4:8]==bytes.fromhex('28b52ffd'):return zstandard.ZstdDecompressor().decompress(b[4:],max_output_size=int.from_bytes(b[:4],'little'))
 return lzma.decompress(b[4:9]+b[:4]+bytes(4)+b[9:],format=lzma.FORMAT_ALONE)
db=index(D/'db.pack')
def get(table):
 t=table+'_tables'
 return decode(table, extract(db, 'db\\'+t+'\\data__'))

def decode(table,b):
 t=table+'_tables'; p=0; ver=0
 if b[:4]==bytes.fromhex('FDFEFCFF'):p=6+2*int.from_bytes(b[4:6],'little')
 if b[p:p+4]==bytes.fromhex('FCFDFeFF'):ver=struct.unpack_from('<i',b,p+4)[0];p+=8
 hdr=b[:p+1]; n=struct.unpack_from('<I',b,p+1)[0];p+=5
 segment=S.split('        "'+t+'": [',1)[1].split('\n        "',1)[0]
 fields=re.search(r'\n                version: '+str(ver)+r',\s+fields: \[(.*?)\n                \],',segment,re.S)[1]
 fields=re.findall(r'name: "(.*?)",\s+field_type: (\w+)',fields)
 rows=[]
 for i in range(n):
  row={}
  for k,ft in fields:
   if ft in ('OptionalStringU8','OptionalStringU16'):
    exists=b[p];p+=1
    if not exists:row[k]=None;continue
   if 'String' in ft:
    l=struct.unpack_from('<H',b,p)[0];p+=2; sz=2 if '16' in ft else 1; row[k]=b[p:p+l*sz].decode('utf-16-le' if sz==2 else 'utf8');p+=l*sz
   else:
    fmt={'Boolean':'B','I32':'i','F32':'f','I16':'h','I64':'q','F64':'d'}[ft];row[k]=struct.unpack_from('<'+fmt,b,p)[0];p+=struct.calcsize(fmt)
  rows.append(row)
 assert p==len(b),(table,p,len(b))
 return fields,rows,hdr
