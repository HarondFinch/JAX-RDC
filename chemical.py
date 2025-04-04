"""
The module extracts thermodynamic parameters 
from Cantera’s database and employs dedicated functions 
to compute critical thermodynamic state variables for gas mixtures: 
gas constant (R), enthalpy (h), specific heat ratio (gamma) and et al.

dependencies: jax & cantera(python version)
"""

import jax.numpy as jnp
from jax import vmap,jit
import nondim
from thermo import get_gibbs,fill_Y
from load import read_reaction_mechanism, get_cantera_coeffs

Rg = 8.314463
P0 = nondim.P0

ReactionParams = read_reaction_mechanism('chem.txt')
thermo_mech = 'gri30.yaml'

species_list = ReactionParams['species']
ns = ReactionParams['num_of_species']
ni = ReactionParams['num_of_inert_species']
na = ns - ni
species_M,Mex,_,_,_,_,_,_,_,_,_,_,_,_,_ = get_cantera_coeffs(species_list,thermo_mech)

    
def reactionConstant_i(T, X, i, k, n):

    A = ReactionParams["A"][i]
    B = ReactionParams["B"][i]
    EakOverRu = ReactionParams["Ea/Ru"][i]
    vf_i = ReactionParams["vf"][i,:,:,:]
    vb_i = ReactionParams["vb"][i,:,:,:]
    vf_ik = vf_i[k,:,:]
    vb_ik = vb_i[k,:,:]
    vsum = ReactionParams["vsum"][i]
    aij = ReactionParams["third_body_coeffs"][i,:,:,:]
    g_j = get_gibbs(T[0,:,:])

    kf_i = A*jnp.power(T,B)*jnp.exp(-EakOverRu/T)
    Keq = jnp.exp(jnp.sum((vb_i-vf_i)*(g_j),axis=0,keepdims=True))*((101325/P0/T)**vsum)
    kb_i = kf_i/Keq

    X = jnp.maximum(X,1e-20*jnp.ones_like(X))
    aij_X_sum = jnp.sum(aij*X,axis=0,keepdims=True)
    aij_X_sum = jnp.maximum(aij_X_sum, jnp.ones_like(aij_X_sum))
    
    X = X[0:na,:,:]

    log_X = jnp.log(X)
    kf = kf_i*jnp.exp(jnp.sum(vf_i*log_X,axis=0,keepdims=True))
    kb = kb_i*jnp.exp(jnp.sum(vb_i*log_X,axis=0,keepdims=True))

    w_kOverM_i = (vb_ik-vf_ik)*aij_X_sum*(kf-kb)
    vb_in = vb_i[n]
    vf_in = vf_i[n]
    ain = ReactionParams["third_body_coeffs"][i,n]
    Mn = species_M[n]
    Xn = jnp.expand_dims(X[n,:,:],0)
    dwk_drhonYn_OverMk_i = (vb_ik-vf_ik)*(kf-kb)*ain/Mn + 1/(Mn*Xn)*(vb_ik-vf_ik)*aij_X_sum*(vf_in*kf-vb_in*kb)

    return w_kOverM_i, dwk_drhonYn_OverMk_i

def reaction_rate_with_derievative(T,X,k,n):
    Mk = species_M[k]
    i = jnp.arange(ReactionParams["num_of_reactions"])
    w_kOverM_i, dwk_drhonYn_OverMk_i = vmap(reactionConstant_i,in_axes=(None,None,0,None,None))(T,X,i,k,n)
    w_k = Mk*jnp.sum(w_kOverM_i,axis=0,keepdims=False)
    dwk_drhonYn = Mk*jnp.sum(dwk_drhonYn_OverMk_i,axis=0,keepdims=False)
    return w_k[0,:,:], dwk_drhonYn[0,:,:]

def construct_matrix_equation(T,X,dt):
    matrix_fcn = vmap(vmap(reaction_rate_with_derievative,in_axes=(None,None,None,0)),in_axes=(None,None,0,None))
    k = jnp.arange(na)
    n = jnp.arange(na)
    w_k, dwk_drhonYn = matrix_fcn(T,X,k,n)
    S = jnp.transpose(w_k[:,0:1,:,:],(2,3,0,1))
    DSDU = jnp.transpose(dwk_drhonYn,(2,3,0,1))
    I = jnp.eye(na)
    A = I/dt - DSDU
    b = S
    return A, b

@jit
def solve_implicit_rate(T,rho,Y,dt):
    Y = fill_Y(Y)
    rhoY = rho*Y
    X = rhoY/Mex
    A, b = construct_matrix_equation(T,X,dt)
    dU = jnp.linalg.solve(A,b)
    return jnp.transpose(dU[:,:,:,0],(2,0,1))
    
    

