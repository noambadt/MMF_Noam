	# -*- coding: utf-8 -*-
"""
Simple module to find numerically the propagation modes and their corresponding propagation constants
of multimode fibers of arbitrary index profiles.

Based on 
- http://wavefrontshaping.net/index.php/tutorials
and
- M. Plöschner, T. Tyc, and T. Čižmár, Nature Photonics Seeing through chaos in multimode fibres 9, 529–535 (2015).
https://doi.org/10.1038/nphoton.2015.112

written by Sebastien M. Popoff
"""

import numpy as np
import matplotlib.pyplot as plt
import scipy.sparse as sparse
from scipy.sparse.linalg import eigsh, eigs
from scipy.linalg import expm
from scipy.special import jv,kv,iv
from scipy.ndimage.interpolation import shift as scipy_shift
from scipy.ndimage.interpolation import rotate as scipy_rotate
import sys, time
from . import SI
from .index_profile import IndexProfile 
from .logger import get_logger

logger = get_logger()

def handleException(excType, excValue, traceback, logger=logger):
    logger.error("Uncaught exception", exc_info=(excType, excValue, traceback))

sys.excepthook = handleException
#%%

#https://docs.scipy.org/doc/numpy-1.13.0/user/basics.subclassing.html
class TransmissionMatrix(np.ndarray):

    def __new__(cls, input_array, npola=1):
        # Input array is an already formed ndarray instance
        # We first cast to be our class type
        obj = np.asarray(input_array).view(cls)
        # add the new attribute to the created instance
        obj.npola = npola
        # Finally, we must return the newly created object:
        return obj

    def __array_finalize__(self, obj):
        # see InfoArray.__array_finalize__ for comments
        if obj is None: return
        self.npola = getattr(obj, 'npola', 1)
        
    def polarization_rotation(self,angle):
        if self.npola == 1: return self
        N=self.shape[0]
        Pola1 = self.view()[:,:N/2]
        Pola2 = self.view()[:,N/2:N]
        
        self.view()[:,:N/2] = Pola1*np.cos(angle)+Pola2*np.sin(angle)
        self.view()[:,N/2:N] = Pola2*np.cos(angle)-Pola1*np.sin(angle)
        return self


class Modes():
    
    def __init__(self):
        self.betas = []
        self.u = []
        self.w = []
        self.modesList = []
        self.number = 0
        self.m = []
        self.l = []
        self.indexProfile = None
        self.profiles = []
        self.modeMatrix = None
        self.wl = None
        
        
    def getModeMatrix(self,npola = 1, shift = None, angle = None):
        '''
        	Returns the matrix containing the mode profiles. 
            Note that while you can set two polarizations, the modes profiles are obtained under a scalar apporoximation.
        	
        	Parameters
        	----------
        	
        	npola : int (1 or 2)
        		number of polarizations considered. For npola = 2, the mode matrix will be a block diagonal matrix.
        		
            shift : list or None
                (slow) value of a coordinate offset, allows to return the mode matrix for a fiber with the center shifted with regard
                to the center of the observation window.
                defaults to None
                
            rotation: float or None
                (slow) angle in radians, allows to rotate the mode matrix with an arbitrary angle.
                Note that the rotation is applied BEFORE the transverse shift.
                defaults to None
                
                
        	Returns
        	-------
        	
        	M : numpy array
    		the matrix representing the basis of the propagating modes.
        '''
        assert(self.profiles)
        if shift is not None:
            assert(len(shift)==2)
    
        N = self.profiles[0].shape[0]
        M = np.zeros((N*npola, npola*self.number), dtype = np.complex128)
        angle = angle/np.pi*180. if (angle is not None) else None
  
        
        for pol in range(npola):
        
            for ind,modeProfile in enumerate(self.profiles):
                
                if (shift is None and angle is None):
                    M[pol*N:(pol+1)*N,pol*self.number+ind] = modeProfile#.reshape(1,self._npoints**2)
                else:
                    mode2D = modeProfile.reshape([self.indexProfile.npoints]*2)
                
                    if angle is not None:
                        mode2D = \
                            scipy_rotate(mode2D.real,angle,reshape=False) + \
                            complex(0,1)*scipy_rotate(mode2D.imag,angle,reshape=False)
                
                    if shift is not None:
                
                        mode2D = \
                            scipy_shift(input=mode2D.real,shift=shift) \
                            + complex(0,1)*scipy_shift(input=mode2D.imag,shift=shift)

                    M[pol*N:(pol+1)*N,pol*self.number+ind] = mode2D.flatten()


        self.modeMatrix = M

        return M     
    
    def getNearDegenerate(self,tol=1e-2,sort=False):
        '''
        Find the groups of near degenerate modes with a given tolerence.
        Optionnaly sort the modes (not implemented).
        '''
        copy_betas = {i:b for i,b in enumerate(self.betas)}
        groups = []
        
        
        while not (len(copy_betas) == 0):
            next_ind = np.min(copy_betas.keys())
            beta0 = copy_betas.pop(next_ind)
            current_group = [next_ind]
            for ind in copy_betas.keys():
                if np.abs(copy_betas[ind]-beta0) <= tol:
                    copy_betas.pop(ind)
                    current_group.append(ind)
            groups.append(current_group)
        
        return groups
            
    
    def getEvolutionOperator(self,npola = 1,curvature = None):
        '''
        Returns the evolution operator B of the fiber. 
        The diagonal of the evolution operator correspond to the propagation constants.
        The off-diagonal terms account for the mode coupling.
        The transmission matrix of the fiber reads exp(iBL) with L the propagation distance.
        For a straight fiber, B is a diagonal matrix.
        
        One can add the effect of curvature to a system solved for a straight fiber.
        It returns then the evolution operator in the basis of the straight fiber modes.
        The calculation is different from directly solving the system for a bent fiber [1]_ [2]_.

        
        
        Parameters
        ----------
        npola : int (1 or 2)
        		number of polarizations considered. 
            defaults to 1
            
        curvature: float (optional)
            curvature (in microns)
            defaults to None
            
        Returns
        -------
        B : numpy array
            The propagation operator
        
        See Also
        --------
            getPropagationMatrix()
        
        Notes
        -----
             
        .. [1]  M. Plöschner, T. Tyc and T. Čižmár, "Seeing through chaos in multimode fibres" 
                Nature Photonics, vol. 9,
                pp. 529–535, 2015.
                
        .. [2]  S. M. Popoff, "Numerical Estimation of Multimode Fiber Modes and Propagation Constants: Part 2, Bent Fibers" 
                http://wavefrontshaping.net/index.php/component/content/article/68-community/tutorials/multimode-fibers/149-multimode-fiber-modes-part-2
                
        '''
        betas_vec = self.betas*npola
        B = np.diag(betas_vec).astype(np.complex128)
        
        if curvature is not None:
            assert(self.wl)
            assert(self.indexProfile)
            try:
                assert(self.curvature == None)
            except:
                logger.error("Adding curvature to the propagation operator requires the system to be solved for a straight fiber!")
                return
            if self.modeMatrix is None:
                self.getModeMatrix(npola = npola)
            M = self.getModeMatrix()
            x = np.diag(self.indexProfile.X.flatten())
            A = M.transpose().conjugate().dot(x).dot(M)
            k0 = 2*np.pi/self.wl

            B = B - np.min(self.indexProfile.n)*k0/curvature*A
            
        return B
        
    
    def getPropagationMatrix(self,distance,npola = 1,curvature = None):
        '''
        Returns the transmission matrix T for a given fiber length in the basis of the fiber modes. 
        Note that while you can set two polarizations, the modes profiles are obtained under a scalar apporoximation.
        For a straight fiber, T is a diagonal matrix.
        
        One can add the effect of curvature to a system solved for a straight fiber.
        It returns then the evolution operator in the basis of the straight fiber modes.
        The calculation is different from directly solving the system for a bent fiber [1]_.
        	
        Parameters
        ----------
        	
        distance : float
        		size of the fiber segment (in meters)
    
        npola : int (1 or 2)
        		number of polarizations considered. For npola = 2, the mode matrix will be a block diagonal matrix.
        		
        curvature : float
            curvature of the fiber segment (in microns)
    
        Returns
        -------
        	
        	T : numpy array
        		The transmission matrix of the fiber.
                
        See Also
        --------
            getEvolutionOperator()
        
        Notes
        -----
             
        .. [1]  M. Plöschner, T. Tyc and T. Čižmár, "Seeing through chaos in multimode fibres" 
                Nature Photonics, vol. 9,
                pp. 529–535, 2015.
        '''
        T = self.getEvolutionOperator(npola,curvature)
        

      
        return expm(complex(0,1)*B*distance)

        

def randomGroupCoupling(groups):
    '''
    Create a unitary matrix accounting for random mode coupling only into given groups of modes.
    '''
    size = np.max([np.max(g) for g in groups])+1
    H = np.zeros([size]*2,dtype=np.complex128)
    
    for g in groups:
        # generate random unitary matrix
        g_size = len(g)
        u,_,__ = np.linalg.svd(np.random.randn(g_size,g_size)+complex(0,1)*np.random.randn(g_size,g_size))
        H[np.ix_(g,g)] = u
        
    return H

def estimateNumModesGRIN(wl,a,NA):
    '''
	Returns a rough estimation of the number of propagating modes of a GRIN fiber.
    See https://www.rp-photonics.com/v_number.html for more details.
	
	Parameters
	----------
	
	wl : float
		Wavelength (in microns)
	a :  float
		Radius of the fiber (in microns)
    NA : float
		Numerical aperture of the fiber
		
	Returns
	-------
	
	N : integer
		Estimation of the number of propagating modes
    '''
    k0 = 2.*np.pi/wl
    V = k0*a*NA
    return np.ceil(V**2/4.).astype(int)

def estimateNumModesSI(wl,a,NA):
    '''
	Returns a rough estimation of the number of propagating modes of a step index fiber.
    See https://www.rp-photonics.com/v_number.html for more details.
	
	Parameters
	----------
	
	wl : float
		Wavelength (in microns)
	a :  float
		Radius of the fiber (in microns)
    NA : float
		Numerical aperture of the fiber
		
	Returns
	-------
	
	N : integer
		Estimation of the number of propagating modes
    '''
    k0 = 2.*np.pi/wl
    V = k0*a*NA
    return np.ceil(V**2/2.).astype(int)

def LPModeProfile(m,psi,u,w,a,npoints,areasize,coordtype='cart',forFFT = 0,inf_profile = False):
    '''
    Linearly polarized mode, see : "Weakly Guiding Fibers" by D. Golge in Applied Optics, 1971
    '''
    
    if (forFFT):
        # If forFFT = 1, the center on the mode is half a pixel shifted for an easier access of the Fourier transform
#        x = -1.*np.arange(npoints/2,-npoints/2,-1)*areasize/npoints+1e-9
        x = np.arange(-npoints/2,npoints/2,1)*areasize/npoints+1e-9
        # x = np.arange(-npoints/2*areasize/npoints,npoints/2*areasize/npoints,areasize/npoints)        
    else:
        x = np.linspace(-areasize/2,areasize/2,npoints)
       
 
    [X,Y]=np.meshgrid(x,x)
    [TH,R] = cart2pol(X,Y)
    
    if inf_profile: # infinite profile
        Et = jv(m,u/a*R)/jv(m,u)*np.cos(m*TH+psi)
    else:
    # Non-zero transverse component
        Et = ( jv(m,u/a*R)/jv(m,u)*np.cos(m*TH+psi)*(R <= a) + \
             kv(m,w/a*R)/kv(m,w)*np.cos(m*TH+psi)*(R > a) )
         

         
    Norm = np.sqrt(np.sum(np.abs(Et)**2))
    
    return Et/Norm*np.sign(Et[npoints//2,npoints//2]),[X,Y]

    
def cart2pol(X, Y):
    '''
	Returns the angular and radial matrices (polar coordinates) correspondng to the input cartesian matrices X and Y.
	
	Parameters
	----------
	
	X : numpy array
		matrix corresponding to the first Cartesian coordinate
	Y :  numpy array
		matrix corresponding to the second Cartesian coordinate
		
	Returns
	-------
	
	TH : numpy array
		matrix corresponding to the theta coordinate
	R : numpy array
		matrix corresponding to the radial coordinate
    '''
    TH = np.arctan2(Y, X)
    R = np.sqrt(X**2 + Y**2)
    return (TH, R)   

#%%

class propagationModeSolver():
    
    def __init__(self):
        self.betas = []
        #self.u = []
        #self.w = []
        self.modes = None
        self.modesList = []
        self.number = 0
        self.m = []
        self.l = []
        self.indexProfile = None
        self.wl = None
        self.last_res = None
        self.poisson = 0.5
        
        logger.debug('Debug mode ON.')
        
    
        
    def setIndexProfile(self,indexProfile):
        self.indexProfile = indexProfile
        
    def setWL(self,wl):
        '''
        Set the wavelength (in microns).
        
        Parameters
	    ----------
	    
	    wl : float
            Wavelength in microns.
        '''
        self.wl = wl
        
    def setPoisson(self,poisson):
        '''
        Set the poisson coefficient. The default value is 0.5 (no effect of compression/dilatation)
        
        Parameters
	    ----------
	    
	    poisson : float
            Poisson coefficient of the fiber material.
        '''
        self.poisson = poisson
        

        
    def solve(self,nmodesMax=6,boundary = 'close',storeData = True,curvature = None, mode = 'default'):
        '''
	    Find the first modes of a multimode fiber. The index profile has to be set.
        Returns a Modes structure containing the mode information.
	    
	    Parameters
	    ----------
	    
	    nmodesMax : int 
		    Maximum number of modes the solver will try to find. 
            This value should be higher than the estimated maximum number of modes if one want to be sure 
            to find all the modes.
            defaults to 6
	    boundary : string
		    boundary type, 'close' or 'periodic'
            EXPERIMENTAL.
            It should not make any difference for propagating modes.
        storeData: bool
            Stores data in the propagationModeSolver object is set to True
            defaults to True
        curvature: float
            Curvature of the fiber in meters
            defaults to None
        mode: string
            
            detauls to 'default'
		    
	    Returns
	    -------
	    
	    modes : Modes
		    Modes object containing all the mode information.
        '''
        assert(self.indexProfile)
        assert(self.wl)
        
        t0 = time.time()
        
        dh = self.indexProfile.dh
        k0 = 2.*np.pi/self.wl
        npoints = self.indexProfile.npoints
        diags = []
        
        ## Construction of the operator
        
        diags.append(-4./dh**2+k0**2*self.indexProfile.n.flatten()**2)
        
        if boundary == 'periodic':
            logger.info('Use periodic boundary condition.')
            diags.append(([1./dh**2]*(npoints-1)+[0.])*(npoints-1)+[1./dh**2]*(npoints-1))
            diags.append(([1./dh**2]*(npoints-1)+[0.])*(npoints-1)+[1./dh**2]*(npoints-1))
            diags.append([1./dh**2]*npoints*(npoints-1))
            diags.append([1./dh**2]*npoints*(npoints-1))
            
            diags.append(([0]*(npoints-1)+[1./dh**2])*(npoints-1)+[0]*(npoints-1))
            diags.append(([0]*(npoints-1)+[1./dh**2])*(npoints-1)+[0]*(npoints-1))
            
            diags.append([1./dh**2]*npoints)
            diags.append([1./dh**2]*npoints)
        elif boundary == 'close':
            logger.info('Use periodic close condition.')
            
            # x parts of the Laplacian
            diags.append(([1./dh**2]*(npoints-1)+[0.])*(npoints-1)+[1./dh**2]*(npoints-1))
            diags.append(([1./dh**2]*(npoints-1)+[0.])*(npoints-1)+[1./dh**2]*(npoints-1))
            # y parts of the Laplacian
            diags.append([1./dh**2]*npoints*(npoints-1))
            diags.append([1./dh**2]*npoints*(npoints-1))
            
            
        if curvature is not None:
            # xi term, 
            # - the 1. term represent the geometrical effect
            # - the term in (1-2*poisson_coeff) represent the effect of compression/dilatation
            # see http://wavefrontshaping.net/index.php/68-community/tutorials/multimode-fibers/149-multimode-fiber-modes-part-2
            #xi = 1.-(self.indexProfile.n.flatten()-1.)/self.indexProfile.n.flatten()*(1.-2.*self.poisson)
            xi = 1.
            curv_term = (1.+2*xi*self.indexProfile.X.flatten()/curvature)
            diags[0] = diags[0]/curv_term
            diags[1] = diags[1]/curv_term[1:]
            diags[2] = diags[2]/curv_term[:-1]
            diags[3] = diags[3]/curv_term[npoints:]
            diags[4] = diags[4]/curv_term[:-npoints]

        logger.info('Note that boundary conditions should not matter for guided modes.')   

            
        
        H = sparse.diags(diags,[0,-1,1,-npoints,npoints], dtype = np.complex128)
        self.H = H
        
        
        beta_min = k0*np.min(self.indexProfile.n)
        beta_max =  k0*np.max(self.indexProfile.n)

        # Finds the eigenvalues of the operator with the greatest real part
        res = eigs(H,k=nmodesMax,which = 'LR')
        
        modes = Modes()
        modes.wl = self.wl
        modes.indexProfile = self.indexProfile
        # select only the propagating modes
        for i,betasq in enumerate(res[0]):
#            if curvature is not None or (betasq > beta_min**2 and betasq < beta_max**2):
             if betasq > beta_min**2 and betasq < beta_max**2:
                modes.betas.append(np.sqrt(betasq))
                modes.number+=1
                modes.profiles.append(res[1][:,i])
                modes.profiles[-1] = modes.profiles[-1]/np.sqrt(np.sum(np.abs(modes.profiles[-1])**2))
                
        logger.info("Solver found %g modes is %0.2f seconds." % (modes.number,time.time()-t0))
        
        if (nmodesMax == modes.number):
            logger.warning('The solver reached the maximum number of modes set.')
            logger.warning('Some propagating modes may be missing.')
        
        if storeData:
            self.modes = modes
            logger.debug('Mode data stored in memory.')

        return modes
    

    
    def saveData(self,outfile,saveArea = None):
        assert(self.modes)
        if not saveArea:
            pass
        betas = self.modes.betas
        mode_profiles = self.modes.profiles[1]
        index_profile = self.indexProfile.n
        X = self.indexProfile.X
        Y = self.indexProfile.X
        np.savez(outfile,
                 betas=betas,
                 mode_profiles=mode_profiles,
                 index_profile=index_profile,
                 X=X,
                 Y=Y)
        logger.info('Data saved to %s.' % outfile)
        


        
        

