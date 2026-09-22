"""Redacted structured operational events; source rows and names are never logged."""
import json
import logging
from datetime import datetime,timezone
logger=logging.getLogger('retail.logistics')
if not logger.handlers:
 handler=logging.StreamHandler();handler.setFormatter(logging.Formatter('%(message)s'));logger.addHandler(handler)
logger.setLevel(logging.INFO);logger.propagate=False

def event(name,**fields):
 allowed={'batch','policy','stock_rows','shipment_rows','decision','basis'}
 logger.info(json.dumps({'time':datetime.now(timezone.utc).isoformat(),'event':name,**{k:v for k,v in fields.items() if k in allowed}},sort_keys=True))
