"""
Patch for datafiles.mapper.Mapper to fix path comparison issues 
between network paths and mapped drives.

Enable with environment variable DATAFILES_FIX_PATH_MOUNTS=1

TODO: Submit PR to datafiles to fix this issue upstream.
"""

import os
from pathlib import Path
from types import MethodType
from loguru import logger

def patch_datafiles():
    """Apply patches to datafiles module to fix path handling (Windows). Enable with DATAFILES_FIX_PATH_MOUNTS=1"""
    # Check if the patch should be applied based on environment variable
    if os.environ.get('DATAFILES_FIX_PATH_MOUNTS', '').lower() not in ('1', 'true', 'yes', 'on'):
        logger.debug("Datafiles path mount patch is disabled. Set DATAFILES_FIX_PATH_MOUNTS=1 to enable.")
        return
        
    try:
        import datafiles
        
        # Create a fixed version of the relpath method
        def patched_relpath(self):
            """Fixed relpath that handles different mount points gracefully."""
            if not self.path:
                return Path(".")
                
            try:
                return Path(os.path.relpath(self.path, Path.cwd()))
            except ValueError:
                # When paths are on different mounts (network path vs mapped drive)
                return self.path
        
        # Patch the class property with our fixed version
        datafiles.mapper.Mapper.relpath = property(patched_relpath)
        
        logger.debug("Successfully patched datafiles.mapper.Mapper.relpath")
        
    except ImportError:
        logger.debug("Could not patch datafiles: module not found")
    except Exception as e:
        logger.debug(f"Failed to apply datafiles patch: {e}")


# Apply the patch immediately when this module is imported
patch_datafiles()