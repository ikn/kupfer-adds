'''Inspiration from the deskbar pidgin plugin and from the gajim kupfer
plugin'''
import dbus

from kupfer.objects import (Leaf, Action, Source, AppLeafContentMixin,
		TextLeaf, TextSource)
from kupfer import pretty
from kupfer import icons
from kupfer.helplib import DbusWeakCallback

__kupfer_name__ = _("Pidgin")
__kupfer_sources__ = ("ContactsSource", )
__kupfer_contents__ = ("ContactsSource", )
__description__ = _("Access to Pidgin Contacts")
__version__ = "0.1"
__author__ = "Chmouel Boudjnah <chmouel@chmouel.com>"
# pylint: disable-msg=W0312


def _create_dbus_connection(activate=False):
	''' Create dbus connection to Pidgin
	@activate: true=starts pidgin if not running
	'''
	interface = None
	obj = None
	sbus = dbus.SessionBus()

	service_name = "im.pidgin.purple.PurpleService"
	obj_name = "/im/pidgin/purple/PurpleObject"
	iface_name = "im.pidgin.purple.PurpleInterface"

	try:
		#check for running pidgin (code from note.py)
		proxy_obj = sbus.get_object('org.freedesktop.DBus', '/org/freedesktop/DBus')
		dbus_iface = dbus.Interface(proxy_obj, 'org.freedesktop.DBus')
		if activate or dbus_iface.NameHasOwner(service_name):
			obj = sbus.get_object(service_name, obj_name)
		if obj:
			interface = dbus.Interface(obj, iface_name)
	except dbus.exceptions.DBusException, err:
		pretty.print_debug(err)
	return interface


def _send_message_to_contact(pcontact, message):
	"""
	Send @message to PidginContact @pcontact
	"""
	interface = _create_dbus_connection()
	if not interface:
		return
	account, jid = pcontact.account, pcontact.jid
	conversation = interface.PurpleConversationNew(1, account, jid)
	im = interface.PurpleConvIm(conversation)
	interface.PurpleConvImSend(im, message)


class OpenChat(Action):
	""" Open Chat Conversation Window with jid """

	def __init__(self):
		Action.__init__(self, _('Open Chat'))

	def activate(self, leaf):
		_send_message_to_contact(leaf, u"")

	def get_icon_name(self):
		return 'stock_person'

class SendMessage (Action):
	""" Send chat message directly from Kupfer """
	def __init__(self):
		Action.__init__(self, _("Send Message..."))

	def activate(self, leaf, iobj):
		_send_message_to_contact(leaf, iobj.object)

	def item_types(self):
		yield PidginContact
	def requires_object(self):
		return True
	def object_types(self):
		yield TextLeaf
	def object_source(self, for_item=None):
		return TextSource()

class PidginContact(Leaf):
	""" Leaf represent single contact from Pidgin """

	def __init__(self, jid, name, account, icon, protocol, availability,
		status_message):
		obj = (account, jid)
		Leaf.__init__(self, obj, name or jid)

		if name:
			self._description = "%s <%s>" % (name, jid)
		else:
			self._description = name

		if availability == 0:
			self._description += " - N/A"

		self._description += " - %s" % protocol
		if status_message:
			self._description += "\n%s" % status_message

		self.account = account
		self.name = name
		self.jid = jid
		self.icon = icon

	def get_actions(self):
		yield OpenChat()
		yield SendMessage()

	def get_description(self):
		return self._description

	def get_thumbnail(self, width, height):
		if not self.icon:
			return
		return icons.get_pixbuf_from_file(self.icon, width, height)

	def get_icon_name(self):
		return "pidgin"


class ContactsSource(AppLeafContentMixin, Source):
	''' Get contacts from all on-line accounts in Pidgin via DBus '''
	appleaf_content_id = 'pidgin'

	def __init__(self):
		Source.__init__(self, _('Pidgin Contacts'))
		self.all_buddies = {}
		self._get_all_buddies()
		self._signal_online_offline_buddies()

	def _get_pidgin_contact(self, interface, buddy, account=None, protocol=None):
		if not account:
			account = interface.PurpleBuddyGetAccount(buddy)

		if not protocol:
			protocol = interface.PurpleAccountGetProtocolName(account)

		jid = interface.PurpleBuddyGetName(buddy)
		name = interface.PurpleBuddyGetAlias(buddy)
		_icon = interface.PurpleBuddyGetIcon(buddy)
		icon = None
		if _icon != 0:
			icon = interface.PurpleBuddyIconGetFullPath(_icon)
		presenceid = interface.PurpleBuddyGetPresence(buddy)
		statusid = interface.PurplePresenceGetActiveStatus(presenceid)
		availability = interface.PurplePresenceIsAvailable(presenceid)
		status_message = interface.PurpleStatusGetAttrString(statusid, "message")

		return PidginContact(jid, name, account, icon,
				     protocol, availability,
				     status_message)

	def _get_all_buddies(self):
		interface = _create_dbus_connection()
		if interface is None:
			return

		accounts = interface.PurpleAccountsGetAllActive()
		for account in accounts:
			buddies = interface.PurpleFindBuddies(account, dbus.String(''))
			protocol = interface.PurpleAccountGetProtocolName(account)

			for buddy in buddies:
				if not interface.PurpleBuddyIsOnline(buddy):
					continue

				jid = interface.PurpleBuddyGetName(buddy)
				name = interface.PurpleBuddyGetAlias(buddy)
				_icon = interface.PurpleBuddyGetIcon(buddy)
				icon = None
				if _icon != 0:
					icon = interface.PurpleBuddyIconGetFullPath(_icon)

				self.all_buddies[buddy] = self._get_pidgin_contact(interface,
										   buddy,
										   protocol=protocol,
										   account=account)

	def _buddy_signed_on(self, buddy):
		interface = _create_dbus_connection()
		if not buddy in self.all_buddies:
			self.all_buddies[buddy] = self._get_pidgin_contact(interface, buddy)

	def _buddy_signed_off(self, buddy):
		if buddy in self.all_buddies:
			del self.all_buddies[buddy]

	def _signal_online_offline_buddies(self):
		'''Add signals to pidgin when buddy goes offline or
		online to update the list'''
		try:
			session_bus = dbus.Bus()
		except dbus.DBusException:
			return
		buddy_sign_on_cb = DbusWeakCallback(self._buddy_signed_on)
		buddy_sign_on_cb.token = session_bus.add_signal_receiver(
				buddy_sign_on_cb,
				"BuddySignedOn",
				dbus_interface="im.pidgin.purple.PurpleInterface",
				byte_arrays=True)

		buddy_sign_off_cb = DbusWeakCallback(self._buddy_signed_off)
		buddy_sign_off_cb.token = session_bus.add_signal_receiver(
				buddy_sign_off_cb,
				"BuddySignedOff",
				dbus_interface="im.pidgin.purple.PurpleInterface",
				byte_arrays=True)


	def get_items(self):
		for value in self.all_buddies.values():
			yield value


	def get_icon_name(self):
		return 'pidgin'

	def provides(self):
		yield PidginContact


# Local Variables: ***
# python-indent: 8 ***
# indent-tabs-mode: t ***
# End: ***
