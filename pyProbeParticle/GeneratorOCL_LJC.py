#!/usr/bin/python

# Refrences:
# - Keras Data Generator   https://stanford.edu/~shervine/blog/keras-how-to-generate-data-on-the-fly.html

from __future__ import unicode_literals
import sys
import os
import shutil
import time
import random
import matplotlib;
import numpy as np
from enum import Enum

#import matplotlib.pyplot as plt

import basUtils
#from   import PPPlot 
#import GridUtils as GU
import common    as PPU
#import cpp_utils as cpp_utils

import pyopencl     as cl
import oclUtils     as oclu 
import fieldOCL     as FFcl 
import RelaxOpenCL  as oclr
import HighLevelOCL as hl

import numpy as np
#from keras.utils import Sequence

verbose=1

#class Generator(Sequence):
class Generator():
    preName  = ""
    postName = ""

    n_channels = 1
    n_classes  = 10

    # --- ForceField
    pixPerAngstrome = 10
    iZPP = 8
    Q    = 0.0;
    bPBC = True
    lvec = np.array([
        [ 0.0,  0.0,  0.0],
        [19.0,  0.0,  0.0],
        [ 0.0, 20.0,  0.0],
        [ 0.0,  0.0, 21.0]
    ])

    # --- Relaxation
    npbc       = (1,1,1)
    scan_dim   = ( 100, 100, 20)
    distAbove  =  7.5
    planeShift =  -4.0
    
    # ---- Atom Distance Density
    wr = 1.0
    wz = 1.0
    r2Func = staticmethod( lambda r2 : 1/(1.0+r2) )
    zFunc  = staticmethod( lambda x  : np.exp(-x)  )

    isliceY = -1

    debugPlots = False
    debugPlotSlices   = [0,+2,+4,+6,+8,+10,+12,+14,+16]
    #debugPlotSlices   = [-1]

    'Generates data for Keras'
    def __init__(self, molecules, rotations, batch_size=32 ):
        'Initialization'

        self.molecules = molecules
        self.rotations = rotations
        self.batch_size = batch_size

        #self.dim = dim
        #self.labels = labels
        #self.n_channels = n_channels
        #self.n_classes  = n_classes
        #self.shuffle    = shuffle
        #self.on_epoch_end()

        #rotations = hl.PPU.genRotations( np.array([1.0,0.0,0.0]) , np.linspace(-np.pi/2,np.pi/2, 8) )
        self.counter = 0

        self.typeParams = hl.loadSpecies('atomtypes.ini')
        self.ff_dim     = hl.genFFSampling( self.lvec, self.pixPerAngstrome );  print "ff_dim ",     self.ff_dim
        #self.ff_poss    = FFcl.getposs    ( self.lvec, self.ff_dim );           print "poss.shape ", self.ff_poss.shape  # should we store this?

        self.forcefield = FFcl.ForceField_LJC()

        self.scanner = oclr.RelaxedScanner()
        self.scanner.relax_params = np.array( [ 0.1,0.9,0.1*0.2,0.1*5.0], dtype=np.float32 );
        self.scanner.stiffness    = np.array( [0.24,0.24,0.0, 30.0     ], dtype=np.float32 )/ -16.0217662

    def __len__(self):
        'Denotes the number of batches per epoch'
        return int(np.floor(len(self.list_IDs) / self.batch_size))

    def getMolRotIndex(self, i):
        nrot = len(self.rotations)
        nmol = len(self.molecules)
        return i/(nrot*nmol), (i/nrot)%nmol, i%nrot

    def __getitem__(self, index):
        'Generate one batch of data'
        if(verbose>0): print "index ", index
        n  = self.batch_size
        Xs = np.empty( (n,)+ self.scan_dim     )
        Ys = np.empty( (n,)+ self.scan_dim[:2] )
        for i in range(n):
            ioff = index*n
            iepoch, imol, irot = self.getMolRotIndex( self.counter )
            if(verbose>0): print " imol, irot ", imol, irot
            if( irot == 0 ):# recalc FF
                self.nextMolecule( self.molecules[imol] ) 
                if(self.counter>0): # not first step
                    if(verbose>1): print "scanner.releaseBuffers()"
                    self.scanner.releaseBuffers()
                self.scanner.prepareBuffers( self.FEin, self.lvec, scan_dim=self.scan_dim )
            self.nextRotation( self.rotations[irot], Xs[i], Ys[i] )
            self.counter +=1
        return Xs, Ys

    def nextMolecule(self, fname ):
        fullname = self.preName+fname+self.postName
        if(verbose>0): print " ===== nextMolecule: ", fullname
        t1ff = time.clock();
        atom_lines = open( fullname ).readlines()
        xyzs,Zs,enames,qs = basUtils.loadAtomsLines( atom_lines )
        self.natoms0 = len(Zs)
        if( self.npbc is not None ):
            Zs, xyzs, qs = PPU.PBCAtoms3D( Zs, xyzs, qs, self.lvec[1:], npbc=self.npbc )
        cLJs  = PPU.getAtomsLJ( self.iZPP, Zs, self.typeParams ).astype(np.float32)
        #FF,self.atoms = self.forcefield.makeFF( xyzs, qs, cLJs, poss=self.ff_poss )
        FF,self.atoms = self.forcefield.makeFF( xyzs, qs, cLJs, lvec=self.lvec, pixPerAngstrome=self.pixPerAngstrome )
        self.FEin  = FF[:,:,:,:4] + self.Q*FF[:,:,:,4:];
        Tff = time.clock()-t1ff;   
        if(verbose>1): print "Tff %f [s]" %Tff

    def plot(self,X,Y,Y_=None):
        import matplotlib as mpl;  mpl.use('Agg');
        import matplotlib.pyplot as plt
        iepoch, imol, irot = self.getMolRotIndex( self.counter )
        fname    = self.preName + self.molecules[imol] + ("/rot%03i_" % irot)
        print " plot to file : ", fname

        plt.imshow( Y )
        plt.savefig(  fname+"Dens.png", bbox_inches="tight"  ); 
        plt.close()

        for isl in self.debugPlotSlices:
            #plt.imshow( FEout[:,:,isl,2] )
            plt.imshow(  X[:,:,isl] )
            plt.savefig(  fname+( "Fz_iz%03i.png" %isl ), bbox_inches="tight"  ); 
            plt.close()

            if Y_ is not None:
                plt.imshow ( Y_[:,:,isl] )
                plt.savefig( fname+( "FzFix_iz%03i.png" %isl ), bbox_inches="tight"  ); 
                plt.close()

    def nextRotation(self, rot, X,Y ):
        t1scan = time.clock();
        zDir = rot[2].flat.copy()
        pos0  = hl.posAboveTopAtom( self.atoms[:self.natoms0], zDir, distAbove=self.distAbove )
        poss  = self.scanner.setScanRot( pos0, rot=rot, start=(-10.0,-10.0), end=(10.0,10.0) )
        FEout = self.scanner.run()
        #FEout = self.scanner.runTilted()
        #X[:,:,:] = FEout[:,:,:,2]
        print "rot.shape, zDir.shape", rot.shape, zDir
        print "FEout.shape ", FEout.shape
        X[:,:,:] = FEout[:,:,:,0]*zDir[0] + FEout[:,:,:,1]*zDir[1] + FEout[:,:,:,2]*zDir[2]
        Tscan = time.clock()-t1scan;  
        if(verbose>1): print "Tscan %f [s]" %Tscan
        
        t1y = time.clock();
        '''
        if(verbose>1): print "relax poss.shape", poss.shape
        poss[:,:,:3] += ( rot[2] * self.planeShift )[None,None,:]   # shift toward surface
        self.getDistDens( self.atoms[:,:3], poss[:,:,:3], Y )
        '''
        self.scanner.runFixed( FEout=FEout )
        #Y[:,:] = FEout[:,:,-1,2]
        Y[:,:] =  FEout[:,:,self.isliceY,0]*zDir[0] + FEout[:,:,self.isliceY,1]*zDir[1] + FEout[:,:,self.isliceY,2]*zDir[2]
        Ty =  time.clock()-t1scan;  
        if(verbose>1): print "Ty %f [s]" %Ty

        if(self.debugPlots):
            Y_ = FEout[:,:,:,0]*zDir[0] + FEout[:,:,:,1]*zDir[1] + FEout[:,:,:,2]*zDir[2]
            self.plot(X,Y, Y_ )

    def getDistDens(self, atoms, poss, F):
        F[:,:] = 0
        for atom in atoms[:1]:
            ## TODO - we should project it with respect to rotation
            dposs =  poss - atom[None,None,:]
            #F[:,:] += self.r2Func( (dposs[:,:,0]**2 + dposs[:,:,1]**2)/self.wr ) # * self.zFunc( dposs[:,:,2]/self.wz )
            F[:,:] += self.r2Func( (dposs[:,:,0]**2 + dposs[:,:,1]**2 + dposs[:,:,2]**2 )/self.wr )



