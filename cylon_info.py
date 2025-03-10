#!/usr/bin/env python

"""
Script to query important information from Cylon BACnet controllers including:
- Serial number
- Firmware version
- FLX modules
- Additional diagnostic information
"""

import sys
from bacpypes.debugging import bacpypes_debugging, ModuleLogger
from bacpypes.consolelogging import ConfigArgumentParser
from bacpypes.core import run
from bacpypes.iocb import IOCB
from bacpypes.pdu import Address
from bacpypes.apdu import ReadPropertyRequest, ReadPropertyACK
from bacpypes.primitivedata import Unsigned
from bacpypes.constructeddata import Array
from bacpypes.app import BIPSimpleApplication
from bacpypes.object import get_datatype
from bacpypes.local.device import LocalDeviceObject

# Setup debugging
_debug = 0
_log = ModuleLogger(globals())

class CylonDeviceInfo:
    def __init__(self, device_address, ini_path=None):
        self.address = Address(device_address)
        
        # Parse command line arguments
        args = ConfigArgumentParser(description=__doc__).parse_args()
        
        # Create local device object
        self.this_device = LocalDeviceObject(ini=args.ini)
        
        # Create BACnet application
        self.app = BIPSimpleApplication(self.this_device, args.ini.address)

    async def read_property(self, object_id, property_id, array_index=None):
        """Read a property from the device"""
        try:
            request = ReadPropertyRequest(
                objectIdentifier=object_id,
                propertyIdentifier=property_id
            )
            request.pduDestination = self.address
            
            if array_index is not None:
                request.propertyArrayIndex = array_index

            iocb = IOCB(request)
            self.app.request_io(iocb)
            await iocb.wait()

            if iocb.ioError:
                return f"Error: {str(iocb.ioError)}"

            apdu = iocb.ioResponse
            if not isinstance(apdu, ReadPropertyACK):
                return "Error: Invalid response"

            datatype = get_datatype(apdu.objectIdentifier[0], apdu.propertyIdentifier)
            if not datatype:
                return "Error: Unknown datatype"

            # Handle array properties
            if issubclass(datatype, Array) and (apdu.propertyArrayIndex is not None):
                if apdu.propertyArrayIndex == 0:
                    value = apdu.propertyValue.cast_out(Unsigned)
                else:
                    value = apdu.propertyValue.cast_out(datatype.subtype)
            else:
                value = apdu.propertyValue.cast_out(datatype)

            return value

        except Exception as error:
            return f"Error: {str(error)}"

    async def get_device_info(self):
        """Query and display all relevant device information"""
        # Device object identifier is always (device, instance)
        device_id = ('device', 1)
        
        # List of properties to query
        properties = [
            'modelName',
            'firmwareRevision',
            'serialNumber',
            'description',
            'location',
            'applicationSoftwareVersion',
            'protocolVersion',
            'protocolRevision',
            'objectList'
        ]
        
        print("\nCylon BACnet Controller Information")
        print("===================================")
        print(f"Device Address: {self.address}\n")
        
        for prop in properties:
            value = await self.read_property(device_id, prop)
            if not str(value).startswith('Error'):
                print(f"{prop}: {value}")
            else:
                print(f"{prop}: Not available")

def main():
    if len(sys.argv) < 2:
        print("Usage: python cylon_info.py <device_address>")
        print("Example: python cylon_info.py 192.168.1.160")
        sys.exit(1)

    device_address = sys.argv[1]
    device = CylonDeviceInfo(device_address)
    
    try:
        run(device.get_device_info())
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"\nError: {str(e)}")

if __name__ == "__main__":
    main()
