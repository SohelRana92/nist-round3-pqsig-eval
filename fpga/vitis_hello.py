# vitis_hello.py - Vitis platform (standalone, microblaze_0) and a Hello World
# application from the XSA, without the GUI.
#
#   vitis -s fpga/vitis_hello.py build/fpga_s25/pqsig_mb.xsa build/vitis_ws
import sys
import vitis

xsa, ws = sys.argv[1], sys.argv[2]
client = vitis.create_client()
client.set_workspace(path=ws)

plat = client.create_platform_component(name="pqsig_plat", hw_design=xsa, os="standalone",
                                        cpu="microblaze_0", domain_name="standalone_microblaze_0")
plat.build()
xpfm = client.find_platform_in_repos("pqsig_plat")

app = client.create_app_component(name="hello_world", platform=xpfm,
                                  domain="standalone_microblaze_0", template="hello_world")
app.build()
print("VITIS_DONE")
vitis.dispose()
