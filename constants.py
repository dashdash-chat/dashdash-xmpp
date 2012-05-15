
class Stage:
    IDLE = 1
    ACTIVE = 2
    RETIRED = 3


class ProxybotCommand:
    activate = 'activate'
    retire = 'retire'
    add_participant = 'add_participant'
    remove_participant = 'remove_participant'