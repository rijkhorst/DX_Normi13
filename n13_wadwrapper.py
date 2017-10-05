#!/usr/bin/env python
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# PyWAD is open-source software and consists of a set of modules written in python for the WAD-Software medical physics quality control software. 
# The WAD Software can be found on https://github.com/wadqc
# 
# The pywad package includes modules for the automated analysis of QC images for various imaging modalities. 
# PyWAD has been originaly initiated by Dennis Dickerscheid (AZN), Arnold Schilham (UMCU), Rob van Rooij (UMCU) and Tim de Wit (AMC) 
#
#
# Changelog:
#   20170828: add uniformity thumbnail
#   20170825: fixed misinterpretation of auto_suffix, mustbeinverted, mustbemirrored
#   20170801: added mirror param
#   20170622: identify more float vars from header
#   20170310: add override params; take average over series
#   20161220: Removed class variables; removed testing stuff
#   20160825: fixes for portable detector
#   20160802: removed adding limits (now part of analyzer)
#   20160620: remove quantity and units
#
# ./n13_wadwrapper.py -c Config/dx_philips_wkz1_normi13.json -d TestSet/StudyNormi13 -r results_normi13.json
from __future__ import print_function

__version__ = '20170828'
__author__ = 'aschilham'

import os
if not 'MPLCONFIGDIR' in os.environ:
    os.environ['MPLCONFIGDIR'] = "/tmp/.matplotlib" # if this folder already exists it must be accessible by the owner of WAD_Processor 
import matplotlib
matplotlib.use('Agg') # Force matplotlib to not use any Xwindows backend.

try:
    import pydicom as dicom
except ImportError:
    import dicom
import n13_lib
import numpy as np

# try system package wad_qc
from wad_qc.modulelibs import wadwrapper_lib
from wad_qc.module import pyWADinput

# MODULE EXPECTS PYQTGRAPH DATA: X AND Y ARE TRANSPOSED!

def logTag():
    return "[n13_wadwrapper] "

# helper functions
"""
    roomWKZ1 = n13_lib.Room('WKZ1', pid_tw=[70,50],
                               linepairmarkers={'type':'RXT02',xymm0.6':[-83.,-25.],'xymm1.0':[-99.,-8.]},artefactborderpx=[5,5,5,5],
                               detectorname={'SN152495':'Tafel', 'SN152508':'Wand', 'SN1522YG':'Klein1', 'SN151685':'Groot2'})
    "actions": {
        "acqdatetime": {
            "filters": {}, 
            "params": {}
        }, 
        "header_series": {
            "filters": {}, 
            "params": {
                "detector_names": "SN152495;Tafel|SN152508;Wand", 
                "linepair_type": "typ38", 
                "roomname": "WKZ1", 
                "tablepidmm": 70, 
                "wallpidmm": 50, 
                "xymm0.6": "-108.5;3.8", 
                "xymm1.4": "-87.9;24.2", 
                "xymm1.8": "-81.3;-27.3", 
                "xymm4.6": "-56.2;-2.2"
            }
        }, 
        "qc_series": {
            "filters": {}, 
            "params": {
                "detector_names": "SN152495;Tafel|SN152508;Wand", 
                "linepair_type": "typ38", 
                "roomname": "WKZ1", 
                "tablepidmm": 70, 
                "wallpidmm": 50, 
                "xymm0.6": "-108.5;3.8", 
                "xymm1.4": "-87.9;24.2", 
                "xymm1.8": "-81.3;-27.3", 
                "xymm4.6": "-56.2;-2.2"
            }
        }
"""
def override_settings(room, params):
    """
    Look for 'use_' params in to force behaviour of module and disable automatic determination of param.
    """
    try:
        room.pixmm = float(params['use_pixmm'])
    except:
        pass
    try:
        room.mustbeinverted = (str(params['use_mustbeinverted']).lower() == 'true') 
    except:
        pass
    try:
        room.mustbemirrored = (str(params['mustbemirrored']).lower() == 'true')
    except:
        pass

def _getRoomDefinition(params):
    # Use the params in the config file to construct an Scanner object
    try:
        # a name for identification
        roomname = params['roomname']

        # Need to know the type of linepairs insert
        linepair_type = params['linepair_type']
        if not linepair_type in ['None','RXT02','typ38']:
            raise ValueError('Incorrect linepair type %s'%linepair_type)
        
        # load the locations of markers on the linepair pattern. if these are not given, use the hardcoded values
        linepairmarkers = {}
        try:
            if linepair_type == 'RXT02':
                mnames = ['xymm1.0','xymm0.6']
            elif linepair_type == 'typ38':
                mnames = ['xymm1.8','xymm0.6','xymm1.4','xymm4.6']
                
            for mname in mnames:
                marker  = params[mname]
                vals = [float(v) for v in  marker.split(';')]
                linepairmarkers[mname] = [vals[0],vals[1]]
        except Exception as e:
            print(logTag()+' exact locations of markers on linepair pattern not supplied by config. Using empirical values; please check if these are valid here.')
        linepairmarkers['type'] = linepair_type
        
        # border to exclude
        artefactborderpx = [0,0,0,0]
        try:
            bpxs = params['artefactborderpx']
            artefactborderpx = [int(v) for v in  bpxs.split(';')]
        except:
            print(logTag()+' no border supplied by config. Using [0,0,0,0].')
            
        # load detector names
        detectorname = {}
        try:
            dets_names = params['detector_names']
            for dn in dets_names.split('|'):
                vals = dn.split(';')
                detectorname[vals[0]] = vals[1]
        except:
            print(logTag()+' no explicit detector_name pairs defined in config.')

        # Source to Detector distance and Patient to Detector distance for wall and table (both in mm)
        # is a fixed setting forced?
        try:
            pidmm = [ float(params['pidmm']) ]
        except:
            try:
                # Source to Detector distance and Patient to Detector distance for wall and table (both in mm)
                pidmm = [ float(params['tablepidmm']), float(params['wallpidmm']) ]
            except:
                if not 'use_pixmm' in params:
                    raise KeyError('Must supply "tablepidmm" and "wallpidmm", or "pidmm", or "use_pixmm"')
                else:
                    pidmm = [-1] # will fill in use_pixmm later
        try:
            sidmm = [ float(params['sidmm']) ]
        except:
            try:
                sidmm = [ float(params['tablesidmm']), float(params['wallsidmm']) ]
            except:
                sidmm = [-1, -1] # not supplied

        # do we want a suffix added to the results, based on table/wall or detectorname?
        try:
            auto_suffix = (str(params['auto_suffix']).lower() == 'true')
        except:
            auto_suffix = False
        print(logTag()+' auto_suffix set to ', auto_suffix)
        
        outvalue    = -1 # not supplied
        
        # no artificial thresholds present or needed
        room = n13_lib.Room(roomname, outvalue=outvalue,
                            pid_tw=pidmm, sid_tw=sidmm,
                            artefactborderpx=artefactborderpx,
                            linepairmarkers=linepairmarkers,detectorname=detectorname,auto_suffix=auto_suffix)
        
        override_settings(room, params)
        return room

    except AttributeError as e:
        raise ValueError(logTag()+" missing room definition parameter!"+str(e))


###### Series wrappers
def qc_series(data, results, action):
    """
    n13_UMCU checks:
        XRayEdges
        LowContrast
        DynamicRange
        MTF

    Workflow:
        2. Check data format
        3. Build and populate qcstructure
        4. Run tests
        5. Build xml output
        6. Build artefact picture thumbnail
    """
    try:
        params = action['params']
    except KeyError:
        params = {}

    inputfile = data.series_filelist[0]  # give me a filename

    ## 2. Check data format
    dcmInfile,pixeldataIn,dicomMode = wadwrapper_lib.prepareInput(inputfile,headers_only=False,logTag=logTag())

    # select only middle slice for series
    numslices = len(pixeldataIn)
    if dicomMode == wadwrapper_lib.stMode3D:
        nim = int(len(pixeldataIn)/2.)
        dcmInfile   = dcmInfile._datasets[nim]
        pixeldataIn = np.average(pixeldataIn, axis=0)
        dicomMode = wadwrapper_lib.stMode2D

    ## 3. Build and populate qcstructure
    remark = ""
    qclib = n13_lib.XRayQC()
    room = _getRoomDefinition(params)
    cs = n13_lib.XRayStruct(dcmInfile,pixeldataIn,room)
    cs.verbose = False # do not produce detailed logging

    ## 4. Run tests
    error,msg = qclib.QC(cs)

    ## 5. Build xml output
    ## Struct now contains all the results and we can write these to the WAD IQ database
    if not cs.DetectorSuffix() is None:
        idname = '_'+cs.DetectorSuffix()
    else:
        idname = ''
        
    ## first Build artefact picture thumbnail
    label = 'normi13'
    filename = '%s%s.jpg'%(label,idname) # Use jpg if a thumbnail is desired

    qclib.saveAnnotatedImage(cs, filename, 'normi13')
    varname = '%s%s'%(label,idname)
    results.addObject(varname, filename)

    labvals = qclib.ReportEntries(cs)
    tmpdict={}
    for elem in labvals:
        varname = elem['name']+str(idname)
        results.addFloat(varname, elem['value'])
    results.addFloat('num_slices'+str(idname), numslices)

def qc_uniformity_series(data, results, action):
    """
    n13_uniformity checks:
        Uniformity
        Artefacts
    Workflow:
        2. Check data format
        3. Build and populate qcstructure
        4. Run tests
        5. Build xml output
        6. Build artefact picture thumbnail
    """
    try:
        params = action['params']
    except KeyError:
        params = {}

    inputfile = data.series_filelist[0]  # give me a filename

    ## 2. Check data format
    dcmInfile,pixeldataIn,dicomMode = wadwrapper_lib.prepareInput(inputfile,headers_only=False,logTag=logTag())

    # select only middle slice for series
    numslices = len(pixeldataIn)
    if dicomMode == wadwrapper_lib.stMode3D:
        nim = int(len(pixeldataIn)/2.)
        dcmInfile   = dcmInfile._datasets[nim]
        pixeldataIn = np.average(pixeldataIn, axis=0)
        dicomMode = wadwrapper_lib.stMode2D

    ## 3. Build and populate qcstructure
    remark = ""
    qclib = n13_lib.XRayQC()
    room = _getRoomDefinition(params)
    cs = n13_lib.XRayStruct(dcmInfile,pixeldataIn,room)
    cs.verbose = False # do not produce detailed logging

    ## 4. Run tests
    error,msg = qclib.QCUnif(cs)

    ## 5. Build xml output
    ## Struct now contains all the results and we can write these to the WAD IQ database
    if not cs.DetectorSuffix() is None:
        idname = '_'+cs.DetectorSuffix()
    else:
        idname = ''

    ## First Build artefact picture thumbnail
    label = 'artefacts'
    filename = '%s%s.jpg'%(label,idname) # Use jpg if a thumbnail is desired
    qclib.saveAnnotatedImage(cs, filename, 'artefacts')
    varname = '%s%s'%(label,idname)
    results.addObject(varname, filename)

    ## also add uniformity thumbnail
    label = 'uniformity'
    filename = '%s%s.jpg'%(label,idname) # Use jpg if a thumbnail is desired
    qclib.saveAnnotatedImage(cs, filename, 'uniformity')
    varname = '%s%s'%(label,idname)
    results.addObject(varname, filename)

    labvals = qclib.ReportEntries(cs)
    tmpdict={}
    for elem in labvals:
        varname = elem['name']+str(idname)
        results.addFloat(varname, elem['value'])
    results.addFloat('num_slices'+str(idname), numslices)

def acqdatetime_series(data, results, action):
    """
    Read acqdatetime from dicomheaders and write to IQC database

    Workflow:
        1. Read only headers
    """
    try:
        params = action['params']
    except KeyError:
        params = {}

    ## 1. read only headers
    dcmInfile = dicom.read_file(data.series_filelist[0][0], stop_before_pixels=True)

    dt = wadwrapper_lib.acqdatetime_series(dcmInfile)

    results.addDateTime('AcquisitionDateTime', dt) 


def header_series(data, results, action):
    """
    Read selected dicomfields and write to IQC database

    Workflow:
        1. Read only headers
        2. Run tests
        3. Build xml output
    """
    try:
        params = action['params']
    except KeyError:
        params = {}

    info = 'qcwad'

    ## 1. read only headers
    dcmInfile = dicom.read_file(data.series_filelist[0][0], stop_before_pixels=True)

    ## 2. Run tests
    qclib = n13_lib.XRayQC()
    room = _getRoomDefinition(params)

    ## Table or Wall? from distances and sensitivity; for well defined protocols to be defined in DESCRIPTION field
    cs = n13_lib.XRayStruct(dcmInfile,None,room)
    cs.verbose = False # do not produce detailed logging
    dicominfo = qclib.DICOMInfo(cs,info)
    if not cs.DetectorSuffix() is None:
        idname = '_'+cs.DetectorSuffix()
    else:
        idname = ''

    ## 3. Build xml output
    floatlist = [
        'Exposure (mAs)',
        'Exposure (uAs)',
        'DistanceSourceToDetector (mm)',
        'ExposureTime (ms)',
        'ExposureTime (us)',
        'ImageAreaDoseProduct',
        'Sensitivity',
        'kVp',
        'CollimatorLeft',
        'CollimatorRight',
        'CollimatorUp',
        'CollimatorDown',
        'EntranceDose_mGy',
        'RelativeXRayExposure'
    ]
    offset = -26
    varname = 'pluginversion'+idname
    results.addString(varname, str(qclib.qcversion))
    for elem in dicominfo:
        varname = elem['name']+str(idname)
        if elem['name'] in floatlist:
            try:
                dummy = float(elem['value'])
            except ValueError:
                elem['value'] = -1
            results.addFloat(varname, float(elem['value']))
        else:
            results.addString(varname, str(elem['value'])[:min(len(str(elem['value'])),100)])

    varname = 'room'+idname
    results.addString(varname, cs.forceRoom.name)
    varname = 'stand'+idname
    results.addString(varname, cs.DetectorStand())

if __name__ == "__main__":
    data, results, config = pyWADinput()

    # read runtime parameters for module
    for name,action in config['actions'].items():
        if name == 'acqdatetime':
            acqdatetime_series(data, results, action)

        elif name == 'header_series':
            header_series(data, results, action)
        
        elif name == 'qc_series':
            qc_series(data, results, action)

        elif name == 'uniformity_series':
            qc_uniformity_series(data, results, action)

    #results.limits["minlowhighmax"]["mydynamicresult"] = [1,2,3,4]

    results.write()