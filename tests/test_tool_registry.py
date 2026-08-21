import os, sqlite3, tempfile, unittest
from unittest.mock import patch

class RegistryTests(unittest.TestCase):
 def test_register_deregister_and_filter(self):
  fd,path=tempfile.mkstemp(); os.close(fd)
  conn=sqlite3.connect(path); conn.execute('CREATE TABLE ACCOUNTS (id int)'); conn.commit(); conn.close()
  with patch('mcp_server.tool_registry.get_db_path', return_value=path):
   from mcp_server.tool_registry import register_tool,deregister_tool,enabled_tools
   register_tool('outage',{'name':'diagnostic'}); register_tool('outage',{'name':'dispatch'})
   self.assertEqual([x['name'] for x in enabled_tools('outage',[{'name':'diagnostic'},{'name':'hidden'}])],['diagnostic'])
   deregister_tool('outage','diagnostic'); self.assertEqual(enabled_tools('outage',[{'name':'diagnostic'}]),[])
  os.unlink(path)
