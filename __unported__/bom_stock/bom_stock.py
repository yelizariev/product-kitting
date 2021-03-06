# -*- coding: utf-8 -*-
##############################################################################
#
#    Author: Joel Grand-Guillaume, Guewen Baconnier, Ursa Information Systems
#    Copyright 2010-2012 Camptocamp SA
#    Copyright 2015-Today Ursa Information Systems
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp.osv import fields, osv
import openerp.addons.decimal_precision as dp
from openerp.tools.float_utils import float_round
import pdb


class res_company(osv.osv):
    _inherit = 'res.company'
    _columns = {
        'ref_stock': fields.selection(
            [('real', 'Quantity on Hand'),
             ('virtual', 'Quantity Available'),
             ('immediately', 'Quantity You Can Sell')],
            'Basis for BoM Stock calculations')
        }

    _defaults = {
        'ref_stock': 'immediately',
        }


class product_product(osv.osv):
    """
    Inherit Product in order to add a "BOM Stock" field
    """
    _inherit = 'product.product'

    def _bom_stock_mapping(self, cr, uid, context=None):
        return {'real': 'qty_available',
                'virtual': 'virtual_available',
                'immediately': 'qty_sellable'}

    def _compute_bom_stock(self, cr, uid, product,
                           quantities, company, context=None):
        bom_obj = self.pool['mrp.bom']
        uom_obj = self.pool['product.uom']
        mapping = self._bom_stock_mapping(cr, uid, context=context)
        stock_field = mapping[company.ref_stock]

        product_qty = 0
        # find a bom on the product
        bom_id = bom_obj._bom_find(
            cr, uid, product.product_tmpl_id.id, product.uom_id.id, properties=[])

        if bom_id:
            prod_min_quantities = []
            bom = bom_obj.browse(cr, uid, bom_id, context=context)
            if bom.bom_line_ids:
                stop_compute_bom = False
                # Compute stock qty of each product used in the BoM and
                # get the minimal number of items we can produce with them
                for line in bom.bom_line_ids:
                    prod_min_quantity = 0.0
                    bom_qty = line.product_id[stock_field] # expressed in product UOM
                    # the reference stock of the component must be greater
                    # than the quantity of components required to
                    # build the bom
                    line_product_qty = uom_obj._compute_qty_obj(cr, uid,
                                                                line.product_uom,
                                                                line.product_qty,
                                                                line.product_id.uom_id,
                                                                round = False,
                                                                context=context)
                    if bom_qty >= line_product_qty:
                        prod_min_quantity = bom_qty / line_product_qty  # line.product_qty is always > 0
                    else:
                        # if one product has not enough stock,
                        # we do not need to compute next lines
                        # because the final quantity will be 0.0 in any case
                        stop_compute_bom = True

                    prod_min_quantities.append(prod_min_quantity)
                    if stop_compute_bom:
                        break


                produced_qty = uom_obj._compute_qty_obj(cr, uid,
                                                        bom.product_uom,
                                                        bom.product_qty,
                                                        bom.product_tmpl_id.uom_id,
                                                        round = False,
                                                        context=context)
                product_qty += min(prod_min_quantities) * produced_qty
        return product_qty


    def _product_available(self, cr, uid, ids, field_names=None,
                           arg=False, context=None):
        # We need available, virtual or immediately usable
        # quantity which is selected from company to compute Bom stock Value
        # so we add them in the calculation.
        context = context or {}
        field_names = field_names or []

        user_obj = self.pool['res.users']
        comp_obj = self.pool['res.company']

        res = super(product_product, self)._product_available(
            cr, uid, ids, field_names, arg, context)

        if 'bom_stock' in field_names:
            company = user_obj.browse(cr, uid, uid, context=context).company_id
            if not company:
                company_id = comp_obj.search(cr, uid, [], context=context)[0]
                company = comp_obj.browse(cr, uid, company_id, context=context)

            for product_id, stock_qty in res.iteritems():
                product = self.browse(cr, uid, product_id, context=context)
                res[product_id]['bom_stock'] = \
                    self._compute_bom_stock(
                        cr, uid, product, stock_qty, company, context=context)
        return res


    def _search_product_quantity(self, cr, uid, obj, name, domain, context):
        res = []
        for field, operator, value in domain:
            #to prevent sql injections
            assert field in ('qty_available', 'qty_sellable','virtual_available', 'incoming_qty', 'outgoing_qty'), 'Invalid domain left operand'
            assert operator in ('<', '>', '=', '!=', '<=', '>='), 'Invalid domain operator'
            assert isinstance(value, (float, int)), 'Invalid domain right operand'

            if operator == '=':
                operator = '=='

            product_ids = self.search(cr, uid, [], context=context)
            ids = []
            if product_ids:
                #TODO: use a query instead of this browse record which is probably making the too much requests, but don't forget
                #the context that can be set with a location, an owner...
                for element in self.browse(cr, uid, product_ids, context=context):
                    if eval(str(element[field]) + operator + str(value)):
                        ids.append(element.id)
            res.append(('id', 'in', ids))
        return res


    def _product_sellable_text(self, cr, uid, ids, field_names=None, arg=False, context=None):
        res = {}
        for product in self.browse(cr, uid, ids, context=context):
            res[product.id] = str(product.qty_sellable) +  _(" You Can Sell")
        return res



    _columns = {
        'qty_available': fields.function(_product_available, multi='qty_available',
            type='float', digits_compute=dp.get_precision('Product Unit of Measure'),
            string='Quantity On Hand',
            fnct_search=_search_product_quantity,
            help="Current quantity of products.\n"
                 "In a context with a single Stock Location, this includes "
                 "goods stored at this Location, or any of its children.\n"
                 "In a context with a single Warehouse, this includes "
                 "goods stored in the Stock Location of this Warehouse, or any "
                 "of its children.\n"
                 "stored in the Stock Location of the Warehouse of this Shop, "
                 "or any of its children.\n"
                 "Otherwise, this includes goods stored in any Stock Location "
                 "with 'internal' type."),
        'virtual_available': fields.function(_product_available, multi='qty_available',
            type='float', digits_compute=dp.get_precision('Product Unit of Measure'),
            string='Forecast Quantity',
            fnct_search=_search_product_quantity,
            help="Forecast quantity (computed as Quantity On Hand "
                 "- Outgoing + Incoming)\n"
                 "In a context with a single Stock Location, this includes "
                 "goods stored in this location, or any of its children.\n"
                 "In a context with a single Warehouse, this includes "
                 "goods stored in the Stock Location of this Warehouse, or any "
                 "of its children.\n"
                 "Otherwise, this includes goods stored in any Stock Location "
                 "with 'internal' type."),
        'incoming_qty': fields.function(_product_available, multi='qty_available',
            type='float', digits_compute=dp.get_precision('Product Unit of Measure'),
            string='Incoming',
            fnct_search=_search_product_quantity,
            help="Quantity of products that are planned to arrive.\n"
                 "In a context with a single Stock Location, this includes "
                 "goods arriving to this Location, or any of its children.\n"
                 "In a context with a single Warehouse, this includes "
                 "goods arriving to the Stock Location of this Warehouse, or "
                 "any of its children.\n"
                 "Otherwise, this includes goods arriving to any Stock "
                 "Location with 'internal' type."),
        'outgoing_qty': fields.function(_product_available, multi='qty_available',
            type='float', digits_compute=dp.get_precision('Product Unit of Measure'),
            string='Outgoing',
            fnct_search=_search_product_quantity,
            help="Quantity of products that are planned to leave.\n"
                 "In a context with a single Stock Location, this includes "
                 "goods leaving this Location, or any of its children.\n"
                 "In a context with a single Warehouse, this includes "
                 "goods leaving the Stock Location of this Warehouse, or "
                 "any of its children.\n"
                 "Otherwise, this includes goods leaving any Stock "
                 "Location with 'internal' type."),   
        'qty_sellable_text': fields.function(_product_sellable_text, type='char'),
        'qty_sellable': fields.function(_product_available, multi='qty_available',
            type='float', digits_compute=dp.get_precision('Product Unit of Measure'),
            string='Quantity You Can Sell',
            fnct_search=_search_product_quantity,
            help="Current quantity of products you can Sell.\n"
                 "In a context with a single Stock Location, this includes "
                 "goods stored at this Location, or any of its children.\n"
                 "In a context with a single Warehouse, this includes "
                 "goods stored in the Stock Location of this Warehouse, or any "
                 "of its children.\n"
                 "stored in the Stock Location of the Warehouse of this Shop, "
                 "or any of its children.\n"
                 "Otherwise, this includes goods stored in any Stock Location "
                 "with 'internal' type.  Anything not commited to an existing Sale is counted."),
        'bom_stock': fields.function(_product_available, multi='qty_available',
            type='float', digits_compute=dp.get_precision('Product Unit of Measure'),
            string='Quantity You Can Make',
            fnct_search=_search_product_quantity, 
            help="Quantities of products based on Bill of Materials,"
                 "useful to know how much of this " 
                 "product you could produce. "
                 "Computed as:\n "
                 "Reference stock of this product + "
                 "how much could I produce of this product with the BoM" 
                 "Components",)
    }

class product_template(osv.osv):
    """
    Inherit Product Template in order to add a "BOM Stock" field
    """
    _inherit = 'product.template'

    def _search_product_quantity(self, cr, uid, obj, name, domain, context):
        prod = self.pool.get("product.product")
        res = []
        for field, operator, value in domain:
            #to prevent sql injections
            assert field in ('bom_stock','qty_sellable','qty_available', 'virtual_available', 'incoming_qty', 'outgoing_qty'), 'Invalid domain left operand'
            assert operator in ('<', '>', '=', '!=', '<=', '>='), 'Invalid domain operator'
            assert isinstance(value, (float, int)), 'Invalid domain right operand'

            if operator == '=':
                operator = '=='

            product_ids = prod.search(cr, uid, [], context=context)
            ids = []
            if product_ids:
                #TODO: use a query instead of this browse record which is probably making the too much requests, but don't forget
                #the context that can be set with a location, an owner...
                for element in prod.browse(cr, uid, product_ids, context=context):
                    if eval(str(element[field]) + operator + str(value)):
                        ids.append(element.id)
            res.append(('product_variant_ids', 'in', ids))
        return res

    def _product_available(self, cr, uid, ids, name, arg, context=None):

        res = {}
        res = super(product_template, self)._product_available(
            cr, uid, ids, name, arg, context)

        for product in self.browse(cr, uid, ids, context=context):
            sumq = 0
            for p in product.product_variant_ids:
                sumq += p.qty_available
            res[product.id].update( {
                "bom_stock": sum([p.bom_stock for p in product.product_variant_ids]) or 0,
            } )
        return res


    _columns = {
        'qty_available': fields.function(_product_available, multi='qty_available',
            fnct_search=_search_product_quantity, type='float', string='Quantity On Hand'),
        'virtual_available': fields.function(_product_available, multi='qty_available',
            fnct_search=_search_product_quantity, type='float', string='Quantity Available'),
        'incoming_qty': fields.function(_product_available, multi='qty_available',
            fnct_search=_search_product_quantity, type='float', string='Incoming'),
        'outgoing_qty': fields.function(_product_available, multi='qty_available',
            fnct_search=_search_product_quantity, type='float', string='Outgoing'),    
        'qty_sellable': fields.function(_product_available, multi='qty_available',
            fnct_search=_search_product_quantity, type='float', string='Quantity You Can Sell'),
        
        'bom_stock': fields.function(_product_available, multi='qty_available',
            fnct_search=_search_product_quantity, type='float', string='Quantity You Can Make'),
    }

