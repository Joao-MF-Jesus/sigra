import test from 'node:test';
import assert from 'node:assert/strict';
import { recommendationReview } from '../src/features/recommendations/recommendationWizardModel.js';

test('review names the original default without selecting the derived Base',()=>{
 const value=Object.fromEntries(recommendationReview({multifactor_enabled:true,cost_scenario:'base',fuel_price:'7',multifactor_price_mode:'anp'}));
 assert.match(value['Perfil multifator'],/método original, sete critérios/);
 assert.match(value['Perfil multifator'],/não seleciona a alternativa/);
 assert.match(value['Preço da personalização'],/sem preço manual/);
 assert.match(value['Preço da personalização'],/não o substitui/);
});
test('explicit manual and derived choices remain visible and distinct',()=>{
 const value=Object.fromEntries(recommendationReview({multifactor_enabled:true,fuel_price:'7',multifactor_price_mode:'manual',
  multifactor_manual_fuel_price_brl:'6',multifactor_policy_version:'academic-derived-seven-v1',multifactor_configuration_id:'academic-derived-base-five-v1'}));
 assert.match(value['Rotina'],/referência a R\$ 7/);
 assert.match(value['Preço da personalização'],/R\$ 6\/L/);
 assert.match(value['Perfil multifator'],/Base — cinco dimensões/);
 assert.doesNotMatch(value['Perfil multifator'],/Ativado|aprovado/);
});
