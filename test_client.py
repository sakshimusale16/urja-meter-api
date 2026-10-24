from portal_client import PortalClient

client = PortalClient()
print("Meters:", len(client.get_all_meters()))
print("Transformers:", len(client.get_transformers()))
readings = client.get_consumption("J100000")
print("Readings:", len(readings), "| First:", readings[0])
