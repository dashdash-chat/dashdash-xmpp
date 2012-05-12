import sleekxmpp
from sleekxmpp.stanza import Iq
from sleekxmpp.xmlstream import ET, ElementBase, register_stanza_plugin

class ProxybotInvisibility(ElementBase):

    name = 'query'
    namespace = 'jabber:iq:privacy'
    plugin_attrib = 'proxybot_invisibility'

    def make_list(self, list_name):
        list_xml = ET.Element("{%s}list" % (self.namespace))
        list_xml.attrib['name'] = list_name
        self.xml.append(list_xml)
        
    def make_active(self, list_name=None):
        list_xml = ET.Element("{%s}active" % (self.namespace))
        if list_name:
            list_xml.attrib['name'] = list_name
        self.xml.append(list_xml)
        
    def add_item(self, itype=None, ivalue=None, iaction='allow', iorder=0):    
        presence_xml = ET.Element("{%s}presence-out" % (self.namespace))
        # message_xml = ET.Element("{%s}message" % (self.namespace))
        # iq_xml = ET.Element("{%s}iq" % (self.namespace))
        item_xml = ET.Element("{%s}item" % (self.namespace))
        item_xml.append(presence_xml)
        # item_xml.append(message_xml)
        # item_xml.append(iq_xml)
        if itype:
            item_xml.attrib['type'] = itype
        if ivalue:
            item_xml.attrib['value'] = ivalue
        item_xml.attrib['action'] = iaction
        item_xml.attrib['order'] = str(iorder)
        
        list_xml = self.find("{%s}list" % (self.namespace))
        list_xml.append(item_xml)
        
register_stanza_plugin(Iq, ProxybotInvisibility)

# May now use as so, within the context of a SleekXMPP instance.
# >>> iq = self.Iq()
# >>> iq['gtalk_invisible']['version'] = "2"
# >>> iq['gtalk_invisible']['status'] = "Can't see me!"
# >>> iq['gtalk_invisible']['show'] = "DND"
# >>> iq['gtalk_invisible']['invisible'] = True
# >>> iq.send()
#
# To test interactively, you can use:
# python -i gtalk_invisible.py
# >>> i = Iq()
# >>> ... same as above ...
